"""Adaptador ATPDraw: genera el proyecto DIBUJADO de ATPDraw desde el modelo neutro.

ATPDraw (>= 7.0) abre proyectos en formato XML ("XML text format"), pensado
para intercambio con otros programas. Este adaptador escribe ese XML: cada
elemento de `red.yaml` queda como un componente con posición, nodos y datos,
unido con cables. ATPDraw lo abre ya dibujado, lo puede guardar como `.acp` y
correr con ATP (F2) sin plantilla hecha a mano.

Reglas del formato que hay que respetar (verificadas con ATPDraw 7.8):
  * La conectividad la define la GEOMETRÍA: terminales en la misma coordenada
    o unidos con <conn>. Coordenadas en múltiplos de 10.
  * Un nombre de nodo solo se conserva si lleva UserNamed="true".
  * Un nodo a tierra lleva Ground="1".
  * ATP admite 6 caracteres por nodo y ATPDraw agrega la fase (A/B/C) en los
    nodos trifásicos: los nombres base deben tener a lo sumo 5 caracteres.
  * SATTRAFO: Coupl = tipo*1000 + desfase en grados (tipo 1 = Y, 2 = D). La
    tensión de devanado (kV) es de línea en D y de fase en Y.

Modelo eléctrico (régimen permanente, equivalente al de flujo de cargas):
  * Red externa: fuente trifásica ideal en su barra (slack). En modo falla se
    le agrega la impedancia de la red Zq = c·Un²/Scc y la fuente sube a c·Un
    (IEC 60909, c = 1,1).
  * Línea: R + L serie (RLC3); con capacitancia, PI trifásico (LINEPI3S).
  * Transformador: SATTRAFO de dos devanados con el grupo y el desfase del
    modelo, sin rama de magnetización; la impedancia de cortocircuito va en el
    devanado de BT y el tap modifica la tensión del devanado de su lado.
  * Carga: impedancia constante en estrella a tierra (RLCY3), calculada a la
    tensión indicada en `u_carga_pu` (por defecto 1,0 p.u.).
"""
from __future__ import annotations

import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from ..modelo import Red, Transformador
from .base import Adaptador
from .plantillas_ad import variables

X0, Y0 = 2800, 2700        # origen del lienzo de ATPDraw
PASO_X = 200               # distancia horizontal entre barras consecutivas
PASO_Y = 120               # distancia vertical entre filas de ramas
CAIDA_CARGA = 40           # la carga cuelga 40 unidades bajo su barra
C_IEC = 1.1                # factor de tensión c máximo (IEC 60909)
R_FALLA = 1e-4             # resistencia de la falla franca (ohm)
R_ABIERTO = 1e6            # fase sana en el elemento de falla (ohm)
TIPOS_FALLA = {            # fases falladas (A, B, C) y si la falla va a tierra
    "3f": ((True, True, True), True),
    "1f": ((True, False, False), True),
    "2f": ((False, True, True), False),
    "2ft": ((False, True, True), True),
}


def _f(x: float) -> str:
    return f"{x:.6g}"


class _Lienzo:
    """Acumula componentes, cables y textos del proyecto ATPDraw."""

    def __init__(self):
        self.objetos = ET.Element("objects")
        self._usados: set[str] = set()

    def nombre_nodo(self, base: str) -> str:
        n = re.sub(r"[^A-Z0-9]", "", base.upper())[:5] or "N"
        cand, k = n, 1
        while cand in self._usados:
            sufijo = str(k)
            cand, k = n[: 5 - len(sufijo)] + sufijo, k + 1
        self._usados.add(cand)
        return cand

    def comp(self, nombre: str, x: int, y: int, nodos, datos, extra=None):
        c = ET.SubElement(self.objetos, "comp", Name=nombre)
        cc = ET.SubElement(c, "comp_content", PosX=str(x), PosY=str(y),
                           HighRes="false", Icon="default", **(extra or {}))
        for n in nodos:
            ET.SubElement(cc, "node", **n)
        for nom, unidad, val in datos:
            ET.SubElement(cc, "data", Name=nom, Unit=unidad, Value=str(val))
        return c

    def cable(self, x1: int, y1: int, x2: int, y2: int):
        if (x1, y1) == (x2, y2):
            return
        c = ET.SubElement(self.objetos, "conn")
        ET.SubElement(c, "conn_content", Pos1X=str(x1), Pos1Y=str(y1),
                      Pos2X=str(x2), Pos2Y=str(y2), Color="0")

    def texto(self, x: int, y: int, s: str):
        t = ET.SubElement(self.objetos, "text")
        tc = ET.SubElement(t, "text_content", PosX=str(x), PosY=str(y), FontName="Tahoma",
                           FontSize="9", FontStyle="0", Color="-16777208", Orientation="0",
                           BckCol="16777215", FrmCol="16777215")
        tc.text = s


def _nodo(nombre: str, valor: str, dx: int, dy: int, fases: int = 1, tierra: bool = False,
          deshabilitado: bool = False, kind: int = 1) -> dict[str, str]:
    n = {"Name": nombre, "Value": valor}
    if valor:
        n["UserNamed"] = "true"
    if fases > 1:
        n["NumPhases"] = str(fases)
    n.update(Kind=str(kind), PosX=str(dx), PosY=str(dy), NamePosX="4", NamePosY="-4")
    if tierra:
        n["Ground"] = "1"
    if deshabilitado:
        n["Disabled"] = "true"
    return n


def _rlc3(lz: _Lienzo, x: int, y: int, entrada: str, salida: str, r: float, l_mh: float):
    datos = []
    for k in (1, 2, 3):
        datos += [(f"R_{k}", "Ohms", _f(r)), (f"L_{k}", "XOPT", _f(l_mh)), (f"C_{k}", "COPT", "0")]
    lz.comp("RLC3", x, y, [_nodo("IN1", entrada, -20, 0, 3), _nodo("OUT1", salida, 20, 0, 3)], datos)


def _rlcy3(lz: _Lienzo, x: int, y: int, nodo: str, r, l_mh: float, neutro: str = ""):
    """Estrella R-L por fase. `r` puede ser un número o una terna (A, B, C).
    Sin `neutro` el centro va a tierra; con `neutro` queda flotando con ese nombre."""
    rs = r if isinstance(r, (tuple, list)) else (r, r, r)
    datos = []
    for k in (1, 2, 3):
        datos += [(f"R_{k}", "Ohms", _f(rs[k - 1])), (f"L_{k}", "XOPT", _f(l_mh)), (f"C_{k}", "COPT", "0")]
    lz.comp("RLCY3", x, y, [_nodo("IN", nodo, -20, 0, 3),
                            _nodo("OUT", neutro, 20, 0, tierra=not neutro)], datos)


def _linerl3s(lz: _Lienzo, x: int, y: int, entrada: str, salida: str,
              r1: float, l1_mh: float, r0: float, l0_mh: float):
    """Rama R-L trifásica con acople de secuencias (valores totales: longitud 1 m)."""
    lz.comp("LINERL3S", x, y, [_nodo("IN1", entrada, -20, 0, 3), _nodo("OUT1", salida, 20, 0, 3)],
            [("Ro", "Ohm/m", _f(r0)), ("Lo", "XOPT/m", _f(l0_mh)),
             ("R+", "Ohm/m", _f(r1)), ("L+", "XOPT/m", _f(l1_mh)), ("Length", "m", 1)])


def _acsource(lz: _Lienzo, x: int, y: int, nodo: str, u_ll_kv: float, angulo: float, f_hz: float):
    """Fuente trifásica del catálogo de ATPDraw (Phases=1: trifásica; Scaling=2: V eficaces de línea)."""
    from ..atpdraw_catalogo import componente
    v = _f(u_ll_kv * 1000)
    c = componente("ACSOURCE", x, y, nodos={"AC": nodo}, datos={
        "Kind": 0, "AmplitudeA": v, "AmplitudeB": v, "AmplitudeC": v, "Frequency": _f(f_hz),
        "PhaseAngleA": _f(angulo), "PhaseAngleB": _f(angulo - 120), "PhaseAngleC": _f(angulo + 120),
        "Power": 0, "cosPhi": 0, "StartA": -1, "StartB": -1, "StartC": -1, "StopA": [100, 100, 100],
        "AngleUnit": 0, "Phases": 1, "Scaling": 2, "Grounding": 0})
    for n in c.find("comp_content").iter("node"):  # terminales trifásicos como en los proyectos de ATPDraw
        if n.get("Name") in ("AC", "ACNEG", "Internal"):
            n.set("NumPhases", "3")
    lz.objetos.append(c)


def _devanados(grupo: str) -> tuple[bool, bool, int]:
    """(AT en delta, BT en delta, desfase en grados) a partir de 'Dyn5', 'YNd11', 'Yy0'..."""
    m = re.fullmatch(r"\s*([YDZ])N?\s*([ydz])n?\s*(\d{1,2})\s*", grupo)
    if not m or "Z" in m.group(1) or "z" in m.group(2):
        raise ValueError(f"ATPDraw: grupo de conexión no soportado: {grupo!r}")
    return m.group(1) == "D", m.group(2) == "d", 30 * int(m.group(3)) % 360


def _sattrafo(lz: _Lienzo, x: int, y: int, t: Transformador, at: str, bt: str, tap: int,
              r_bt: float, l_bt_mh: float):
    d_at, d_bt, desfase = _devanados(t.grupo)
    if (t.uk0_pct not in (None, t.uk_pct)) or (t.ukr0_pct not in (None, t.ukr_pct)):
        raise ValueError(f"ATPDraw: {t.id} con uk0 distinto de uk no se puede representar con SATTRAFO")
    factor_tap = 1 + tap * t.tap_paso_pct / 100
    v_at = t.un_at_kV * (factor_tap if t.tap_lado == "at" else 1)
    v_bt = t.un_bt_kV * (factor_tap if t.tap_lado == "bt" else 1)
    v_at = v_at if d_at else v_at / math.sqrt(3)
    v_bt = v_bt if d_bt else v_bt / math.sqrt(3)
    # La impedancia del equivalente en estrella pasa al devanado: x3 si es delta.
    k_bt = 3 if d_bt else 1
    minimo = 1e-6
    nodos = [_nodo("Primary", at, -20, 0, 3), _nodo("Secondary", bt, 20, 0, 3),
             _nodo("Starpoint", "", -10, -20, 3, kind=2),
             _nodo("Prim-N", "", -10, 20, kind=3, tierra=not d_at, deshabilitado=d_at),
             _nodo("Sec-N", "", 10, 20, kind=3, tierra=not d_bt, deshabilitado=d_bt),
             _nodo("Tertiary", "", 0, -20, 3, deshabilitado=True),
             _nodo("Tert-N", "", 10, -20, kind=3, deshabilitado=True)]
    datos = [("I0", "Amps", 0), ("F0", "Wb-t", 0), ("R0", "", 0), ("RM", "ohms", 0),
             ("Vrp", "kV", _f(v_at)), ("Rp", "ohms", _f(minimo)), ("Lp", "XOPT", _f(minimo)),
             ("CouplP", "", 2000 if d_at else 1000),
             ("Vrs", "kV", _f(v_bt)), ("Rs", "ohms", _f(r_bt * k_bt)), ("Ls", "XOPT", _f(l_bt_mh * k_bt)),
             ("CouplS", "", (2000 if d_bt else 1000) + desfase),
             ("Vrt", "kV", 0), ("Rt", "ohms", 0), ("Lt", "XOPT", 0), ("CouplT", "", 1000),
             ("3-wind", "", 0), ("RMS", "", 1)]
    c = lz.comp("SATTRAFO", x, y, nodos, datos, extra={"NumPhases": "7"})
    ET.SubElement(c.find("comp_content"), "nonlin", Kind="8")


def generar_xml(red: Red, escenario: str | None = None,
                u_carga_pu: dict[str, float] | None = None, tmax_s: float = 0.02,
                falla: str | None = None, tipo_falla: str = "3f") -> str:
    """Devuelve el proyecto ATPDraw (XML) del escenario indicado.

    `falla`: id de una barra. Arma el caso de cortocircuito IEC 60909 (impedancia
    de la red, fuente a c·Un, sin cargas, falla franca en esa barra) del tipo
    `tipo_falla`: "3f", "1f" (fase A a tierra), "2f" (B-C) o "2ft" (B-C a tierra)."""
    if tipo_falla not in TIPOS_FALLA:
        raise ValueError(f"tipo de falla '{tipo_falla}' no válido: {sorted(TIPOS_FALLA)}")
    a_tierra = TIPOS_FALLA[tipo_falla][1] and tipo_falla != "3f"
    if falla is not None and a_tierra and (faltan := red.faltantes_secuencia_cero()):
        raise ValueError(f"faltan datos de secuencia cero para la falla {tipo_falla}: " + "; ".join(faltan))
    esc = red.escenario(escenario)
    var = variables(red, esc.id)
    w = 2 * math.pi * red.frecuencia_Hz
    u_carga_pu = u_carga_pu or {}
    lz = _Lienzo()
    nodo = {b.id: lz.nombre_nodo(b.id) for b in red.barras}
    if falla is not None and falla not in nodo:
        raise KeyError(f"barra de falla '{falla}' no existe")

    # Árbol radial desde la barra de la red externa: ubicación por profundidad y fila.
    raiz = red.redes_externas[0].barra
    hijos: dict[str, list] = {b.id: [] for b in red.barras}
    visto, cola = {raiz}, [raiz]
    while cola:
        a = cola.pop(0)
        for rid, b1, b2, obj in red.ramas():
            if a in (b1, b2):
                b = b2 if a == b1 else b1
                if b not in visto:
                    visto.add(b)
                    hijos[a].append((rid, b, obj))
                    cola.append(b)
    if len(visto) != len(red.barras):
        raise ValueError("ATPDraw: hay barras aisladas de la red externa; el dibujo es radial")

    filas: dict[str, int] = {}

    def contar(b: str) -> int:
        filas[b] = max(1, sum(contar(h) for _, h, _ in hijos[b]))
        return filas[b]

    contar(raiz)
    pos: dict[str, tuple[int, int]] = {}

    def ubicar(b: str, x: int, y: int):
        pos[b] = (x, y)
        yh = y
        for _, h, _ in hijos[b]:
            ubicar(h, x + PASO_X, yh)
            yh += filas[h] * PASO_Y

    ubicar(raiz, X0, Y0)

    # Red externa: fuente ideal pegada a su barra; en falla, con su impedancia.
    for xr in red.redes_externas:
        bx, by = pos[xr.barra]
        un = red.barra(xr.barra).un_kV
        if falla is None:
            _acsource(lz, bx - 60, by, nodo[xr.barra], un * xr.u_pu, xr.angulo_deg, red.frecuencia_Hz)
            lz.cable(bx - 40, by, bx, by)
        else:
            interno = lz.nombre_nodo(f"{xr.id}F")
            zq = C_IEC * un ** 2 / xr.scc_max_MVA
            xq = zq / math.sqrt(1 + xr.r_x_max ** 2)
            _acsource(lz, bx - 140, by, interno, un * C_IEC, xr.angulo_deg, red.frecuencia_Hz)
            if xr.x0_x1 is None or xr.r0_x0 is None:
                _rlc3(lz, bx - 80, by, interno, nodo[xr.barra], xq * xr.r_x_max, xq / w * 1000)
            else:
                xq0 = xq * xr.x0_x1
                _linerl3s(lz, bx - 80, by, interno, nodo[xr.barra], xq * xr.r_x_max, xq / w * 1000,
                          xq0 * xr.r0_x0, xq0 / w * 1000)
            lz.cable(bx - 120, by, bx - 100, by)
            lz.cable(bx - 60, by, bx, by)
            lz.texto(bx - 100, by - 30, xr.id)

    cargas_por_barra: dict[str, list] = {}
    if falla is None:  # IEC 60909 desprecia las cargas
        for c in red.cargas:
            cargas_por_barra.setdefault(c.barra, []).append(c)
    lineas = {l.id: l for l in red.lineas}

    for b, (bx, by) in pos.items():
        # Punto donde arrancan las ramas de las filas inferiores (debajo de la carga, si hay).
        bajada = (bx, by)
        for c in cargas_por_barra.get(b, []):
            un = red.barra(b).un_kV * u_carga_pu.get(b, 1.0)
            p, q = c.p_MW * esc.escala_carga, c.q_Mvar * esc.escala_carga
            s2 = p ** 2 + q ** 2
            r = un ** 2 * p / s2 if s2 else 1e6
            l_mh = un ** 2 * q / s2 / w * 1000 if s2 else 0.0
            yc = bajada[1] + CAIDA_CARGA
            lz.cable(bx, bajada[1], bx, yc)
            _rlcy3(lz, bx + 20, yc, nodo[b], r, l_mh)
            lz.texto(bx + 44, yc - 6, c.id)
            bajada = (bx, yc)
        if b == falla:
            fases, tierra = TIPOS_FALLA[tipo_falla]
            yc = bajada[1] + CAIDA_CARGA
            lz.cable(bx, bajada[1], bx, yc)
            _rlcy3(lz, bx + 20, yc, nodo[b], tuple(R_FALLA if f else R_ABIERTO for f in fases), 0.0,
                   neutro="" if tierra else lz.nombre_nodo("FALLN"))
            lz.texto(bx + 44, yc - 6, f"FALLA {tipo_falla.upper()}")
            bajada = (bx, yc)

        for i, (rid, h, obj) in enumerate(hijos[b]):
            hx, hy = pos[h]
            # Primera rama sale a la derecha; las demás bajan por la columna de la barra.
            ox, oy = (bx, by) if i == 0 else (bx, hy)
            if i > 0:
                lz.cable(*bajada, ox, oy)
                bajada = (ox, oy)
            if rid in lineas:
                l = lineas[rid]
                lz.cable(ox, oy, ox + 60, oy)
                if l.c_nF_km > 0:
                    r_m = l.r_a(esc.temperatura_C) / 1000 / l.paralelos
                    l_m = l.x_ohm_km / w / l.paralelos              # H/km = mH/m
                    c_m = l.c_nF_km * 1e-6 * l.paralelos            # nF/km -> µF/m
                    c0_m = (l.c0_nF_km * 1e-6 * l.paralelos) if l.c0_nF_km is not None else c_m
                    r0 = (l.r0_ohm_km / 1000 / l.paralelos) if l.r0_ohm_km is not None else r_m
                    l0 = (l.x0_ohm_km / w / l.paralelos) if l.x0_ohm_km is not None else l_m
                    lz.comp("LINEPI3S", ox + 80, oy,
                            [_nodo("In", nodo[b], -20, 0, 3), _nodo("Out", nodo[h], 20, 0, 3)],
                            [("R0", "Ohm/m", _f(r0)), ("L0", "XOPT/m", _f(l0)), ("C0", "COPT/m", _f(c0_m)),
                             ("R+", "Ohm/m", _f(r_m)), ("L+", "XOPT/m", _f(l_m)), ("C+", "COPT/m", _f(c_m)),
                             ("Length", "m", _f(l.longitud_km * 1000))],
                            extra={"NumPhases": "3"})
                elif l.r0_ohm_km is not None and l.x0_ohm_km is not None:
                    _linerl3s(lz, ox + 80, oy, nodo[b], nodo[h],
                              float(var[f"LINEA_{rid}_R_OHM"]), float(var[f"LINEA_{rid}_L_MH"]),
                              l.r0_ohm_km * l.longitud_km / l.paralelos,
                              l.x0_ohm_km * l.longitud_km / l.paralelos / w * 1000)
                else:
                    _rlc3(lz, ox + 80, oy, nodo[b], nodo[h],
                          float(var[f"LINEA_{rid}_R_OHM"]), float(var[f"LINEA_{rid}_L_MH"]))
                lz.cable(ox + 100, oy, hx, hy)
            else:
                t = obj
                if b != t.barra_at:
                    raise ValueError(f"ATPDraw: {t.id} debe alimentarse por su lado de AT")
                lz.cable(ox, oy, ox + 60, oy)
                _sattrafo(lz, ox + 80, oy, t, nodo[b], nodo[h], esc.taps.get(t.id, t.tap_pos),
                          float(var[f"TRAFO_{t.id}_R_BT_OHM"]), float(var[f"TRAFO_{t.id}_L_BT_MH"]))
                lz.cable(ox + 100, oy, hx, hy)
            lz.texto(ox + 60, oy - 30, rid)

    for b, (bx, by) in pos.items():
        # Sonda de tensión trifásica sobre la barra: ATP exige al menos una salida.
        sonda = lz.comp("PROBE_V", bx, by - 20, [_nodo("OUT", nodo[b], 0, 20, 3)],
                        [("Scale", "", 1), ("Freq", "", 0), ("Time", "", 0)])
        pr = ET.SubElement(sonda, "probe", CaptureSteadyState="true", OnScreen="0",
                           ScreenFormat="0", ScreenShow="0", CurrNode="false", FontSize="9",
                           Precision="6", TimeOnScreen="false")
        for fase in (1, 2, 3):
            ET.SubElement(pr, "monitor", Phase=str(fase))
        lz.texto(bx - 30, by - 30, nodo[b])
    ybajo = max(y for _, y in pos.values()) + 2 * PASO_Y
    titulo = f"{red.proyecto} - escenario {esc.id}"
    if falla:
        titulo += f" - falla {tipo_falla.upper()} en {falla} (IEC 60909, c = {C_IEC})"
    lz.texto(X0 - 60, ybajo, titulo + " (generado por power-studies)")

    proyecto = ET.Element("project", Application="ATPDraw", Version="7", VersionXML="1")
    cab = ET.SubElement(proyecto, "header", Timestep="1E-5", Tmax=_f(tmax_s), XOPT="0", COPT="0",
                        EPSILN="0", SysFreq=_f(red.frecuencia_Hz), TopLeftX=str(X0 - 180),
                        TopLeftY=str(Y0 - 60))
    ET.SubElement(cab, "header_output", IOUT="500", IPLOT="1", ICAT="1", MEMSAVE="0",
                  AutoError="false", AutoCode="0", IDOUBLE="1", KSSOUT="1", MAXOUT="1")
    ET.SubElement(cab, "header_format", SORT_C="true", SORT_O="false", SORT_X="false",
                  FORCE_V="false", AutoPath="false", AutoCode="0", ExactPE="false",
                  PL4Comments="false", TACSHybrid="false")
    proyecto.append(lz.objetos)
    ET.SubElement(proyecto, "variables", NumSim="1", IOPCVP="0", UseParser="false")
    ET.indent(proyecto, space="  ")
    return '<?xml version="1.0"?>\n' + ET.tostring(proyecto, encoding="unicode") + "\n"


_NUM = r"(-?\d*\.?\d+(?:E[-+]?\d+)?)"
_FILA_NODO = re.compile(rf"^\s*([A-Z0-9]{{2,6}})\s+{_NUM}\s+{_NUM}")
_FILA_RAMA = re.compile(rf"^\s*([A-Z0-9]{{2,6}})\s+{_NUM}\s+{_NUM}\s+{_NUM}\s+{_NUM}")
_FILA_IMAG = re.compile(rf"^\s+{_NUM}\s+{_NUM}")


def _tabla_permanente(ruta: str | Path) -> list[str]:
    lineas = Path(ruta).read_text(encoding="latin-1").splitlines()
    try:
        ini = next(i for i, l in enumerate(lineas) if "Sinusoidal steady-state phasor solution" in l)
    except StopIteration:
        raise ValueError(f"{ruta}: sin solución de régimen permanente (¿ATP falló?)") from None
    return lineas[ini:]


def leer_lis(ruta: str | Path, red: Red) -> dict[str, tuple[float, float]]:
    """Tensiones de barra (u_pu, ángulo en grados, fase A) del régimen permanente de ATP.

    Lee la tabla "Sinusoidal steady-state phasor solution" del .lis (requiere
    KSSOUT=1, que el XML generado ya pide)."""
    lineas = _tabla_permanente(ruta)
    lz = _Lienzo()
    nodo = {lz.nombre_nodo(b.id): b for b in red.barras}
    out: dict[str, tuple[float, float]] = {}
    for i in range(len(lineas) - 1):
        m = _FILA_NODO.match(lineas[i])
        if not m or not m.group(1).endswith("A") or m.group(1)[:-1] not in nodo:
            continue
        b = nodo[m.group(1)[:-1]]
        ang = _FILA_IMAG.match(lineas[i + 1])
        pico = b.un_kV * 1000 * math.sqrt(2) / math.sqrt(3)
        out.setdefault(b.id, (float(m.group(3)) / pico, float(ang.group(2)) if ang else 0.0))
    return out


def leer_falla(ruta: str | Path, red: Red, barra: str) -> float:
    """Corriente de cortocircuito (kA eficaces) del caso `falla=barra`: la mayor de las
    tres fases de la rama de falla (la que va de la barra a TERRA o al neutro FALLN)."""
    lineas = _tabla_permanente(ruta)
    nombres = {b.id: n for b, n in zip(red.barras, _nombres(red))}
    fases = {nombres[barra] + f for f in "ABC"}
    corrientes = []
    for i in range(len(lineas) - 3):
        m = _FILA_RAMA.match(lineas[i])
        if m and m.group(1) in fases:
            for j in range(i + 2, min(i + 5, len(lineas))):
                destino = lineas[j].strip().split(" ")[0]
                if destino == "TERRA" or destino.startswith("FALLN"):
                    corrientes.append(float(m.group(5)) / math.sqrt(2) / 1000)
                    break
    if not corrientes:
        raise ValueError(f"{ruta}: no se encontró la rama de falla de {barra}")
    return max(corrientes)


def _nombres(red: Red) -> list[str]:
    lz = _Lienzo()
    return [lz.nombre_nodo(b.id) for b in red.barras]


class ATPDrawAdaptador(Adaptador):
    nombre = "atpdraw"
    capacidades = ("exportar", "grafico")

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None,
                 u_carga_pu: dict[str, float] | None = None,
                 falla: str | None = None, tipo_falla: str = "3f") -> list[Path]:
        from ..atpdraw_catalogo import retroalimentar
        retroalimentar()  # aprende de proyectos XML nuevos antes de generar
        carpeta.mkdir(parents=True, exist_ok=True)
        esc = red.escenario(escenario)
        base = unicodedata.normalize("NFKD", red.proyecto).encode("ascii", "ignore").decode()
        base = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_").lower()
        sufijo = f"_falla{tipo_falla}_{falla}" if falla else ""
        ruta = carpeta / f"{base}_{esc.id}{sufijo}.xml"
        ruta.write_text(generar_xml(red, esc.id, u_carga_pu, falla=falla, tipo_falla=tipo_falla), encoding="utf-8")
        return [ruta]
