"""Adaptador DIgSILENT PowerFactory.

PowerFactory solo corre en Windows con licencia, así que el adaptador
trabaja en dos mitades:

  - Aquí (cualquier equipo): `exportar()` prepara una carpeta con el modelo
    neutro en JSON (con posiciones del unifilar) y los scripts que corren
    dentro de PowerFactory. `desde_exportacion()` convierte lo que exporta
    `pf_exportar_modelo.py` de un proyecto existente al modelo neutro.
  - En el Windows con PowerFactory: `pf_construir_red.py` (GUI) o
    `pf_motor.py` (sin GUI) construyen la red, dibujan el unifilar, simulan y
    devuelven `resultados_powerfactory.json` en el formato común.

Si este proceso corre en el mismo equipo que PowerFactory (variable de
entorno PF_PROYECTO definida y módulo `powerfactory` accesible), `flujo()`
ejecuta todo directamente.
"""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path

from ..diagrama import auto_layout
from ..modelo import Red
from ..resultados import Resultados
from .base import Adaptador

SCRIPTS = Path(__file__).resolve().parents[2] / "herramientas" / "powerfactory"


class PowerFactoryAdaptador(Adaptador):
    nombre = "powerfactory"
    capacidades = ("flujo", "cortocircuito", "exportar", "grafico")
    local = False

    def disponible(self):
        if not os.environ.get("PF_PROYECTO"):
            return False, ("PowerFactory se ejecuta en su equipo Windows: use "
                           "`power-studies exportar --herramienta powerfactory` y corra pf_motor.py")
        try:
            import sys
            if os.environ.get("PF_PYTHON"):
                sys.path.append(os.environ["PF_PYTHON"])
            import powerfactory  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "módulo powerfactory no encontrado (defina PF_PYTHON)"

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None) -> list[Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        auto_layout(red)
        modelo = carpeta / "modelo.json"
        red.guardar(modelo)
        rutas = [modelo]
        for f in ("pf_construir_red.py", "pf_motor.py", "pf_exportar_modelo.py"):
            shutil.copy(SCRIPTS / f, carpeta / f)
            rutas.append(carpeta / f)
        (carpeta / "LEAME.txt").write_text(
            "1. Copie esta carpeta al Windows donde está PowerFactory.\n"
            "2. Opción GUI: active el proyecto destino, cree un ComPython apuntando a "
            "pf_construir_red.py, ajuste MODELO_JSON a la ruta de modelo.json y ejecútelo.\n"
            "3. Opción sin GUI: python pf_motor.py --proyecto \"<proyecto>\" --modelo modelo.json\n"
            "4. Devuelva resultados_powerfactory.json para el informe y la validación cruzada.\n",
            encoding="utf-8")
        return rutas

    def flujo(self, red: Red, escenario: str | None = None) -> Resultados:
        ok, motivo = self.disponible()
        if not ok:
            raise RuntimeError(motivo)
        import sys
        import tempfile

        import powerfactory
        sys.path.append(str(SCRIPTS))
        import pf_construir_red as pfc

        app = powerfactory.GetApplicationExt()
        if app.ActivateProject(os.environ["PF_PROYECTO"]):
            raise RuntimeError("no se pudo activar " + os.environ["PF_PROYECTO"])
        auto_layout(red)
        with tempfile.TemporaryDirectory() as tmp:
            m = Path(tmp) / "modelo.json"
            r = Path(tmp) / "res.json"
            red.guardar(m)
            pfc.ESCENARIO = red.escenario(escenario).id
            pfc.main(app, str(m), str(r))
            return Resultados.cargar(r)

    cortocircuito = flujo  # pf_construir_red corre ambos


def desde_exportacion(ruta_json: str | Path) -> Red:
    """Convierte la salida de pf_exportar_modelo.py al modelo neutro."""
    d = json.loads(Path(ruta_json).read_text(encoding="utf-8"))
    f = 60.0
    pos = {}
    for g in d.get("graficos", []):
        if g.get("elemento") and g.get("x") is not None:
            pos.setdefault(g["elemento"], {"x": g["x"], "y": g["y"]})

    barras = [{"id": b["nombre"], "un_kV": b["un_kV"], **({"pos": pos[b["nombre"]]} if b["nombre"] in pos else {})}
              for b in d["barras"]]
    lineas = []
    for l in d.get("lineas", []):
        t = l["tipo"]
        lineas.append({
            "id": l["nombre"], "desde": l["desde"], "hasta": l["hasta"],
            "longitud_km": l["longitud_km"], "paralelos": int(l.get("paralelos") or 1),
            "r_ohm_km": t["r_ohm_km"], "x_ohm_km": t["x_ohm_km"],
            "c_nF_km": (t.get("b_uS_km") or 0) * 1e3 / (2 * math.pi * f),
            "in_kA": t["in_kA"], "r0_ohm_km": t.get("r0_ohm_km"), "x0_ohm_km": t.get("x0_ohm_km"),
            "tipo": "cable" if t.get("es_cable") in (0, None) else "aerea",
            "conductor": t.get("nombre"), "temperatura_ref_C": 20})
    trafos = []
    for tr in d.get("transformadores", []):
        t = tr["tipo"]
        grupo = f"{t.get('conexion_at') or 'D'}{(t.get('conexion_bt') or 'yn').lower()}{t.get('desfase') or 0}"
        trafos.append({
            "id": tr["nombre"], "barra_at": tr["barra_at"], "barra_bt": tr["barra_bt"],
            "sn_MVA": t["sn_MVA"], "un_at_kV": t["un_at_kV"], "un_bt_kV": t["un_bt_kV"],
            "uk_pct": t["uk_pct"], "pcu_kW": t["pcu_kW"], "p0_kW": t.get("p0_kW") or 0,
            "i0_pct": t.get("i0_pct") or 0, "grupo": grupo, "tap_pos": int(tr.get("tap") or 0),
            "tap_paso_pct": t.get("tap_paso_pct") or 2.5,
            "tap_min": int(t.get("tap_min") or -2), "tap_max": int(t.get("tap_max") or 2)})
    cargas = [{"id": c["nombre"], "barra": c["barra"], "p_MW": c["p_MW"], "q_Mvar": c["q_Mvar"]}
              for c in d.get("cargas", [])]
    xnets = [{"id": x["nombre"], "barra": x["barra"], "u_pu": x.get("u_pu") or 1.0,
              "angulo_deg": x.get("angulo_deg") or 0.0, "scc_max_MVA": x.get("scc_max_MVA") or 100,
              "r_x_max": x.get("r_x_max") or 0.1} for x in d.get("redes_externas", [])]
    ref = None
    rf = d.get("resultados_flujo", {})
    if rf.get("convergio"):
        ref = {"fuente": "PowerFactory (pf_exportar_modelo.py)",
               "base": {"u_pu": {k: v["u_pu"] for k, v in rf["barras"].items()},
                        "cargabilidad_pct": {k: v["cargabilidad_pct"] for k, v in rf["ramas"].items()}}}
    return Red.model_validate({
        "proyecto": d.get("proyecto") or "proyecto PowerFactory", "barras": barras,
        "redes_externas": xnets, "lineas": lineas, "transformadores": trafos, "cargas": cargas,
        "referencia": ref, "descripcion": f"Exportado de PowerFactory, caso {d.get('caso_estudio')}"})
