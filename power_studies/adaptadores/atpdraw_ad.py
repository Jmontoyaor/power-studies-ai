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

Modelo eléctrico (régimen permanente, equivalente al de flujo de cargas):
  * Red externa: fuente trifásica ideal en su barra (slack).
  * Línea: R + L serie por fase (RLC3); la capacitancia no se modela aún.
  * Transformador: ideal Y-Y (TRAFO_I3) con la relación del tap + impedancia
    de cortocircuito serie del lado de BT. Sin desfase (grupo Dyn no se dibuja).
  * Carga: impedancia constante en estrella a tierra (RLCY3), calculada a la
    tensión indicada en `u_carga_pu` (por defecto 1,0 p.u.).
"""
from __future__ import annotations

import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

from ..modelo import Red
from .base import Adaptador
from .plantillas_ad import variables

X0, Y0 = 2800, 2700        # origen del lienzo de ATPDraw
PASO_X = 200               # distancia horizontal entre barras consecutivas
PASO_Y = 120               # distancia vertical entre filas de ramas
CAIDA_CARGA = 40           # la carga cuelga 40 unidades bajo su barra


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
          deshabilitado: bool = False) -> dict[str, str]:
    n = {"Name": nombre, "Value": valor}
    if valor:
        n["UserNamed"] = "true"
    if fases > 1:
        n["NumPhases"] = str(fases)
    n.update(Kind="1", PosX=str(dx), PosY=str(dy), NamePosX="4", NamePosY="-4")
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


def _acsource(lz: _Lienzo, x: int, y: int, nodo: str, u_ll_kv: float, angulo: float, f_hz: float):
    v = _f(u_ll_kv * 1000)  # Scaling=2: amplitud en V eficaces de línea
    datos = [("Kind", "Volt/Curr", 0), ("AmplitudeA", "SOURCE", v), ("AmplitudeB", "SOURCE", v),
             ("AmplitudeC", "SOURCE", v), ("Frequency", "Hz", _f(f_hz)),
             ("PhaseAngleA", "degrees", _f(angulo)), ("PhaseAngleB", "degrees", _f(angulo - 120)),
             ("PhaseAngleC", "degrees", _f(angulo + 120)), ("Power", "VA", 0), ("cosPhi", "-1..+1", 0),
             ("StartA", "sec", -1), ("StartB", "sec", -1), ("StartC", "sec", -1),
             ("StopA", "sec", 100), ("StopA", "sec", 100), ("StopA", "sec", 100),
             ("AngleUnit", "0/1", 0), ("Phases", "0/1/2", 1), ("Scaling", "0/1/2", 2),
             ("Grounding", "0/1", 0)]
    lz.comp("ACSOURCE", x, y, [_nodo("AC", nodo, 20, 0, 3)], datos)


def generar_xml(red: Red, escenario: str | None = None,
                u_carga_pu: dict[str, float] | None = None, tmax_s: float = 0.02) -> str:
    """Devuelve el proyecto ATPDraw (XML) del escenario indicado."""
    esc = red.escenario(escenario)
    var = {k: v for k, v in variables(red, esc.id).items()}
    w = 2 * math.pi * red.frecuencia_Hz
    u_carga_pu = u_carga_pu or {}
    lz = _Lienzo()
    nodo = {b.id: lz.nombre_nodo(b.id) for b in red.barras}

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

    # Red externa: fuente ideal pegada a su barra.
    for xr in red.redes_externas:
        bx, by = pos[xr.barra]
        _acsource(lz, bx - 60, by, nodo[xr.barra], red.barra(xr.barra).un_kV * xr.u_pu,
                  xr.angulo_deg, red.frecuencia_Hz)
        lz.cable(bx - 40, by, bx, by)

    cargas_por_barra: dict[str, list] = {}
    for c in red.cargas:
        cargas_por_barra.setdefault(c.barra, []).append(c)

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
            datos = []
            for k in (1, 2, 3):
                datos += [(f"R_{k}", "Ohms", _f(r)), (f"L_{k}", "XOPT", _f(l_mh)), (f"C_{k}", "COPT", "0")]
            lz.comp("RLCY3", bx + 20, yc, [_nodo("IN", nodo[b], -20, 0, 3),
                                           _nodo("OUT", "", 20, 0, tierra=True)], datos)
            lz.texto(bx + 44, yc - 6, c.id)
            bajada = (bx, yc)

        for i, (rid, h, obj) in enumerate(hijos[b]):
            hx, hy = pos[h]
            # Primera rama sale a la derecha; las demás bajan por la columna de la barra.
            ox, oy = (bx, by) if i == 0 else (bx, hy)
            if i > 0:
                lz.cable(*bajada, ox, oy)
                bajada = (ox, oy)
            if rid in {l.id for l in red.lineas}:
                lz.cable(ox, oy, ox + 60, oy)
                _rlc3(lz, ox + 80, oy, nodo[b], nodo[h],
                      float(var[f"LINEA_{rid}_R_OHM"]), float(var[f"LINEA_{rid}_L_MH"]))
                lz.cable(ox + 100, oy, hx, hy)
            else:
                t = obj
                interno = lz.nombre_nodo(f"{t.id}S")
                at, bt = (nodo[b], nodo[h]) if b == t.barra_at else (nodo[h], nodo[b])
                if b != t.barra_at:
                    raise ValueError(f"ATPDraw: {t.id} debe alimentarse por su lado de AT")
                lz.cable(ox, oy, ox + 40, oy)
                lz.comp("TRAFO_I3", ox + 60, oy,
                        [_nodo("P", at, -20, 0, 3), _nodo("PN", "", -10, 20, tierra=True),
                         _nodo("S", interno, 20, 0, 3), _nodo("SN", "", 10, 20, tierra=True)],
                        [("n", "", _f(float(var[f"TRAFO_{t.id}_RELACION"])))],
                        extra={"NumPhases": "4"})
                lz.cable(ox + 80, oy, ox + 100, oy)
                _rlc3(lz, ox + 120, oy, interno, bt,
                      float(var[f"TRAFO_{t.id}_R_BT_OHM"]), float(var[f"TRAFO_{t.id}_L_BT_MH"]))
                lz.cable(ox + 140, oy, hx, hy)
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
    lz.texto(X0 - 60, ybajo, f"{red.proyecto} - escenario {esc.id} (generado por power-studies)")

    proyecto = ET.Element("project", Application="ATPDraw", Version="7", VersionXML="1")
    cab = ET.SubElement(proyecto, "header", Timestep="1E-5", Tmax=_f(tmax_s), XOPT="0", COPT="0",
                        EPSILN="0", SysFreq=_f(red.frecuencia_Hz), TopLeftX=str(X0 - 100),
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
_FILA_IMAG = re.compile(rf"^\s+{_NUM}\s+{_NUM}")


def leer_lis(ruta: str | Path, red: Red) -> dict[str, tuple[float, float]]:
    """Tensiones de barra (u_pu, ángulo en grados, fase A) del régimen permanente de ATP.

    Lee la tabla "Sinusoidal steady-state phasor solution" del .lis (requiere
    KSSOUT=1, que el XML generado ya pide)."""
    lineas = Path(ruta).read_text(encoding="latin-1").splitlines()
    try:
        ini = next(i for i, l in enumerate(lineas) if "Sinusoidal steady-state phasor solution" in l)
    except StopIteration:
        raise ValueError(f"{ruta}: sin solución de régimen permanente (¿ATP falló?)") from None
    lz = _Lienzo()
    nodo = {lz.nombre_nodo(b.id): b for b in red.barras}
    out: dict[str, tuple[float, float]] = {}
    for i in range(ini, len(lineas) - 1):
        m = _FILA_NODO.match(lineas[i])
        if not m or not m.group(1).endswith("A") or m.group(1)[:-1] not in nodo:
            continue
        b = nodo[m.group(1)[:-1]]
        ang = _FILA_IMAG.match(lineas[i + 1])
        pico = b.un_kV * 1000 * math.sqrt(2) / math.sqrt(3)
        out.setdefault(b.id, (float(m.group(3)) / pico, float(ang.group(2)) if ang else 0.0))
    return out


class ATPDrawAdaptador(Adaptador):
    nombre = "atpdraw"
    capacidades = ("exportar", "grafico")

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None,
                 u_carga_pu: dict[str, float] | None = None) -> list[Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        esc = red.escenario(escenario)
        base = unicodedata.normalize("NFKD", red.proyecto).encode("ascii", "ignore").decode()
        base = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_").lower()
        ruta = carpeta / f"{base}_{esc.id}.xml"
        ruta.write_text(generar_xml(red, esc.id, u_carga_pu), encoding="utf-8")
        return [ruta]
