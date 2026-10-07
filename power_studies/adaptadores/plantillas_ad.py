"""Adaptadores por PLANTILLA: ATP/ATPDraw, ETAP y PVsyst.

Estas herramientas no tienen una API abierta y estable para construir el
modelo desde cero (o depende de la licencia). La estrategia robusta es:

  1. El ingeniero dibuja UNA VEZ el caso tipo en la herramienta (con su
     unifilar, símbolos y configuración) y lo guarda como plantilla, poniendo
     marcadores {{VARIABLE}} donde van los parámetros.
  2. El adaptador calcula las variables desde el modelo neutro y genera una
     copia de la plantilla por estudio/escenario.
  3. La herramienta abre o corre esa copia (ATP en lote; PVsyst en modo
     batch; ETAP importando las tablas).

Así la parte gráfica la conserva la propia plantilla del ingeniero.
"""
from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..modelo import Red
from .base import Adaptador

MARCADOR = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*(?:\|\s*(\d+)\s*)?\}\}")


def variables(red: Red, escenario: str | None = None) -> dict[str, str]:
    """Variables comunes para cualquier plantilla. Nombres: TIPO_ID_PARAM."""
    esc = red.escenario(escenario)
    w = 2 * math.pi * red.frecuencia_Hz
    v: dict[str, float | str] = {"PROYECTO": red.proyecto, "ESCENARIO": esc.id,
                                 "FREC_HZ": red.frecuencia_Hz, "TEMP_C": esc.temperatura_C}
    for b in red.barras:
        v[f"BARRA_{b.id}_KV"] = b.un_kV
        v[f"BARRA_{b.id}_VPICO_FN"] = b.un_kV * 1000 * math.sqrt(2) / math.sqrt(3)
    for x in red.redes_externas:
        un = red.barra(x.barra).un_kV
        zcc = un ** 2 / x.scc_max_MVA
        rx = x.r_x_max
        xcc = zcc / math.sqrt(1 + rx ** 2)
        v.update({f"RED_{x.id}_VPICO": un * 1000 * math.sqrt(2) / math.sqrt(3) * x.u_pu,
                  f"RED_{x.id}_R_OHM": xcc * rx, f"RED_{x.id}_L_MH": xcc / w * 1000,
                  f"RED_{x.id}_SCC_MVA": x.scc_max_MVA})
    for l in red.lineas:
        r = l.r_a(esc.temperatura_C) * l.longitud_km / l.paralelos
        x_ = l.x_ohm_km * l.longitud_km / l.paralelos
        v.update({f"LINEA_{l.id}_R_OHM": r, f"LINEA_{l.id}_L_MH": x_ / w * 1000,
                  f"LINEA_{l.id}_C_UF": l.c_nF_km * l.longitud_km * l.paralelos / 1000,
                  f"LINEA_{l.id}_LONG_KM": l.longitud_km, f"LINEA_{l.id}_IN_A": l.in_kA * 1000})
    for t in red.transformadores:
        zb_bt = t.un_bt_kV ** 2 / t.sn_MVA
        r = t.ukr_pct / 100 * zb_bt
        x_ = math.sqrt(max(t.uk_pct ** 2 - t.ukr_pct ** 2, 0)) / 100 * zb_bt
        tap = esc.taps.get(t.id, t.tap_pos)
        v.update({f"TRAFO_{t.id}_KVA": t.sn_MVA * 1000, f"TRAFO_{t.id}_KV_AT": t.un_at_kV,
                  f"TRAFO_{t.id}_KV_BT": t.un_bt_kV, f"TRAFO_{t.id}_UK_PCT": t.uk_pct,
                  f"TRAFO_{t.id}_PCU_KW": t.pcu_kW, f"TRAFO_{t.id}_R_BT_OHM": r,
                  f"TRAFO_{t.id}_L_BT_MH": x_ / w * 1000, f"TRAFO_{t.id}_GRUPO": t.grupo,
                  f"TRAFO_{t.id}_RELACION": t.un_at_kV * (1 + tap * t.tap_paso_pct / 100) / t.un_bt_kV})
    for c in red.cargas:
        un = red.barra(c.barra).un_kV
        p, q = c.p_MW * esc.escala_carga, c.q_Mvar * esc.escala_carga
        s2 = p ** 2 + q ** 2
        # impedancia serie equivalente por fase (estrella) a tensión nominal
        r = un ** 2 * p / s2 if s2 else 1e6
        x_ = un ** 2 * q / s2 if s2 else 0
        v.update({f"CARGA_{c.id}_KW": p * 1000, f"CARGA_{c.id}_KVAR": q * 1000,
                  f"CARGA_{c.id}_R_OHM": r, f"CARGA_{c.id}_L_MH": x_ / w * 1000})
    for g in red.generadores_pv:
        v.update({f"PV_{g.id}_KW": g.p_MW * 1000, f"PV_{g.id}_KVA": g.sn_MVA * 1000})
    return {k: (f"{val:.6g}" if isinstance(val, float) else str(val)) for k, val in v.items()}


def rellenar(texto: str, vars_: dict[str, str], ancho_fijo: bool = False) -> tuple[str, list[str]]:
    """Reemplaza {{VAR}} o {{VAR|ancho}}.

    En formatos de columnas fijas (tarjetas ATP) use {{VAR|6}}: el valor se
    escribe alineado a la derecha en exactamente 6 columnas. Escriba la línea de
    la plantilla como si el campo midiera ese ancho."""
    faltan = []

    def rep(m):
        k = m.group(1)
        if k not in vars_:
            faltan.append(k)
            return m.group(0)
        val = vars_[k]
        if m.group(2):
            val = _numero_ancho(val, int(m.group(2)))
        elif ancho_fijo:
            val = _numero_ancho(val, len(m.group(0)))
        return val

    return MARCADOR.sub(rep, texto), faltan


def _numero_ancho(val: str, n: int) -> str:
    """Formatea un número para que quepa en n columnas (tarjetas ATP)."""
    try:
        x = float(val)
    except ValueError:
        return val[:n].rjust(n)
    for dec in range(n, -1, -1):
        s = f"{x:.{dec}f}"
        if len(s) <= n:
            return s.rjust(n)
    return f"{x:.{max(n - 6, 1)}E}"[:n].rjust(n)


class _PlantillaBase(Adaptador):
    capacidades = ("exportar", "grafico")
    local = True
    extension = ""
    ancho_fijo = False

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None,
                 plantilla: Path | None = None) -> list[Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        vars_ = variables(red, escenario)
        rutas = []
        tabla = carpeta / f"variables_{self.nombre}.csv"
        with tabla.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["variable", "valor"])
            w.writerows(sorted(vars_.items()))
        rutas.append(tabla)
        if plantilla:
            txt = Path(plantilla).read_text(encoding="latin-1")
            out, faltan = rellenar(txt, vars_, self.ancho_fijo)
            if faltan:
                raise KeyError(f"la plantilla usa variables que el modelo no define: {sorted(set(faltan))}")
            destino = carpeta / f"{Path(plantilla).stem}_{red.escenario(escenario).id}{Path(plantilla).suffix}"
            destino.write_text(out, encoding="latin-1")
            rutas.append(destino)
        return rutas


class ATPAdaptador(_PlantillaBase):
    """ATP-EMTP. La plantilla es el .atp que genera ATPDraw (ATP > Make File)
    con marcadores {{...}} de exactamente el ancho de la columna a llenar.
    Si ATP_EXE apunta a tpbig.exe/runATP, corre la simulación en lote."""
    nombre = "atp"
    ancho_fijo = True

    def correr(self, archivo_atp: Path) -> Path:
        exe = os.environ.get("ATP_EXE") or shutil.which("tpbig") or shutil.which("runATP")
        if not exe:
            raise RuntimeError("defina ATP_EXE con la ruta de tpbig.exe / runATP")
        subprocess.run([exe, str(archivo_atp)], cwd=archivo_atp.parent, check=True)
        return archivo_atp.with_suffix(".pl4")


class ETAPAdaptador(_PlantillaBase):
    """ETAP. Genera tablas por tipo de elemento para la importación de datos
    (DataX / Excel) de ETAP; las columnas se ajustan al formato de importación
    de su versión en `plantillas/etap/columnas.csv`."""
    nombre = "etap"

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None,
                 plantilla: Path | None = None) -> list[Path]:
        rutas = super().exportar(red, carpeta, escenario, plantilla)
        from openpyxl import Workbook
        wb = Workbook()
        wb.remove(wb.active)
        hojas = {
            "Buses": (["ID", "Nominal kV", "X", "Y"],
                      [[b.id, b.un_kV, b.pos.x if b.pos else "", b.pos.y if b.pos else ""] for b in red.barras]),
            "Utilities": (["ID", "Bus", "Vpu", "MVAsc", "X/R"],
                          [[x.id, x.barra, x.u_pu, x.scc_max_MVA, 1 / x.r_x_max] for x in red.redes_externas]),
            "Cables": (["ID", "From", "To", "Length m", "R ohm/km", "X ohm/km", "Ampacity A", "Size"],
                       [[l.id, l.desde, l.hasta, l.longitud_km * 1000, l.r_ohm_km, l.x_ohm_km, l.in_kA * 1000,
                         l.conductor or ""] for l in red.lineas]),
            "Transformers": (["ID", "Prim Bus", "Sec Bus", "kVA", "Prim kV", "Sec kV", "%Z", "X/R", "Conn"],
                             [[t.id, t.barra_at, t.barra_bt, t.sn_MVA * 1000, t.un_at_kV, t.un_bt_kV, t.uk_pct,
                               math.sqrt(max(t.uk_pct ** 2 - t.ukr_pct ** 2, 0)) / t.ukr_pct if t.ukr_pct else 99,
                               t.grupo] for t in red.transformadores]),
            "Loads": (["ID", "Bus", "kW", "kvar"],
                      [[c.id, c.barra, c.p_MW * 1000, c.q_Mvar * 1000] for c in red.cargas]),
        }
        for nombre, (enc, filas) in hojas.items():
            ws = wb.create_sheet(nombre)
            ws.append(enc)
            for f in filas:
                ws.append(f)
        ruta = carpeta / "etap_importacion.xlsx"
        wb.save(ruta)
        return rutas + [ruta]


class PVsystAdaptador(_PlantillaBase):
    """PVsyst. Genera el CSV de parámetros para el modo 'Batch' de PVsyst a
    partir de un proyecto/variante plantilla del ingeniero (los reportes y
    gráficas los produce PVsyst)."""
    nombre = "pvsyst"

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None,
                 plantilla: Path | None = None) -> list[Path]:
        rutas = super().exportar(red, carpeta, escenario, plantilla)
        ruta = carpeta / "pvsyst_batch.csv"
        with ruta.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Ident", "Pnom_kWp", "Pnom_inv_kVA", "Barra", "Comentario"])
            for g in red.generadores_pv:
                w.writerow([g.id, g.p_MW * 1000, g.sn_MVA * 1000, g.barra, g.nota or ""])
        return rutas + [ruta]
