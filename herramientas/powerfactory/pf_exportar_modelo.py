# -*- coding: utf-8 -*-
"""
pf_exportar_modelo.py  -  Adaptador PowerFactory -> modelo neutro (paso 1)

Extrae del proyecto ACTIVO de DIgSILENT PowerFactory:
  - la red (barras, lineas/cables, transformadores, cargas, red externa) con sus tipos
  - la posicion de cada elemento en el diagrama unifilar (para poder redibujarlo)
  - los resultados del flujo de cargas
y lo guarda todo en un JSON (modelo neutro) que luego usan los agentes.

USO (dentro de PowerFactory):
  1. Active el proyecto "subestaciones 75 kva" y su caso de estudio.
  2. Cree un script de Python (ComPython) que apunte a este archivo y ejecutelo.
  3. El JSON queda en la ruta SALIDA (abajo). Envieme ese archivo.

Solo LEE el proyecto: no modifica nada (aparte de correr el flujo de cargas).
"""
import json
import os
try:
    import powerfactory
except ImportError:
    powerfactory = None

SALIDA = os.path.join(os.path.expanduser("~"), "Documents", "modelo_neutro_75kva.json")

def attr(obj, nombre, defecto=None):
    """Lee un atributo sin romper el script si no existe en esta version."""
    if obj is None:
        return defecto
    try:
        v = obj.GetAttribute(nombre)
        if hasattr(v, "loc_name"):          # referencia a otro objeto
            return v.loc_name
        return v
    except Exception:
        return defecto


def barra(cubiculo):
    """Nombre de la barra a la que esta conectado un cubiculo (StaCubic)."""
    try:
        return cubiculo.cterm.loc_name if cubiculo and cubiculo.cterm else None
    except Exception:
        return None


def exportar(app, salida=SALIDA):
    app.ClearOutputWindow()
    modelo = {
        "proyecto": attr(app.GetActiveProject(), "loc_name"),
        "caso_estudio": attr(app.GetActiveStudyCase(), "loc_name"),
        "version_powerfactory": app.GetVersion() if hasattr(app, "GetVersion") else None,
        "barras": [], "lineas": [], "transformadores": [], "cargas": [], "redes_externas": [],
        "graficos": [], "resultados_flujo": {"barras": {}, "ramas": {}},
    }

    # ---------------- Red ----------------
    for t in app.GetCalcRelevantObjects("*.ElmTerm"):
        modelo["barras"].append({"nombre": t.loc_name, "un_kV": attr(t, "uknom")})

    for l in app.GetCalcRelevantObjects("*.ElmLne"):
        tipo = l.typ_id
        modelo["lineas"].append({
            "nombre": l.loc_name,
            "desde": barra(l.bus1), "hasta": barra(l.bus2),
            "longitud_km": attr(l, "dline"), "paralelos": attr(l, "nlnum"),
            "tipo": {
                "nombre": attr(tipo, "loc_name"),
                "un_kV": attr(tipo, "uline"), "in_kA": attr(tipo, "sline"),
                "r_ohm_km": attr(tipo, "rline"), "x_ohm_km": attr(tipo, "xline"),
                "b_uS_km": attr(tipo, "bline"),
                "r0_ohm_km": attr(tipo, "rline0"), "x0_ohm_km": attr(tipo, "xline0"),
                "es_cable": attr(tipo, "cohl_"),
            },
        })

    for tr in app.GetCalcRelevantObjects("*.ElmTr2"):
        tipo = tr.typ_id
        modelo["transformadores"].append({
            "nombre": tr.loc_name,
            "barra_at": barra(tr.bushv), "barra_bt": barra(tr.buslv),
            "tap": attr(tr, "nntap"),
            "tipo": {
                "nombre": attr(tipo, "loc_name"),
                "sn_MVA": attr(tipo, "strn"),
                "un_at_kV": attr(tipo, "utrn_h"), "un_bt_kV": attr(tipo, "utrn_l"),
                "uk_pct": attr(tipo, "uktr"), "pcu_kW": attr(tipo, "pcutr"),
                "p0_kW": attr(tipo, "pfe"), "i0_pct": attr(tipo, "curmg"),
                "conexion_at": attr(tipo, "tr2cn_h"), "conexion_bt": attr(tipo, "tr2cn_l"),
                "desfase": attr(tipo, "nt2ag"),
                "tap_paso_pct": attr(tipo, "dutap"),
                "tap_min": attr(tipo, "ntpmn"), "tap_max": attr(tipo, "ntpmx"),
            },
        })

    for c in app.GetCalcRelevantObjects("*.ElmLod"):
        modelo["cargas"].append({
            "nombre": c.loc_name, "barra": barra(c.bus1),
            "p_MW": attr(c, "plini"), "q_Mvar": attr(c, "qlini"),
            "s_MVA": attr(c, "slini"), "fp": attr(c, "coslini"),
        })

    for x in app.GetCalcRelevantObjects("*.ElmXnet"):
        modelo["redes_externas"].append({
            "nombre": x.loc_name, "barra": barra(x.bus1),
            "tipo_barra": attr(x, "bustp"), "u_pu": attr(x, "usetp"),
            "angulo_deg": attr(x, "phiini"),
            "scc_max_MVA": attr(x, "snss"), "r_x_max": attr(x, "rntxn"),
            "scc_min_MVA": attr(x, "snssmin"), "r_x_min": attr(x, "rntxnmin"),
        })

    # ---------------- Diagrama unifilar ----------------
    proyecto = app.GetActiveProject()
    for diagrama in proyecto.GetContents("*.IntGrfnet", 1):
        for g in diagrama.GetContents("*.IntGrf", 0):
            obj = attr(g, "pDataObj")
            modelo["graficos"].append({
                "diagrama": diagrama.loc_name,
                "elemento": obj,
                "simbolo": attr(g, "sSymNam"),
                "x": attr(g, "rCenterX"), "y": attr(g, "rCenterY"),
                "rotacion": attr(g, "iRot"),
                "ancho": attr(g, "rSizeX"), "alto": attr(g, "rSizeY"),
            })

    # ---------------- Flujo de cargas ----------------
    ldf = app.GetFromStudyCase("ComLdf")
    error = ldf.Execute()
    modelo["resultados_flujo"]["convergio"] = (error == 0)
    if error == 0:
        for t in app.GetCalcRelevantObjects("*.ElmTerm"):
            modelo["resultados_flujo"]["barras"][t.loc_name] = {
                "u_pu": attr(t, "m:u"), "ul_kV": attr(t, "m:Ul"), "angulo_deg": attr(t, "m:phiu"),
            }
        for r in (app.GetCalcRelevantObjects("*.ElmLne") + app.GetCalcRelevantObjects("*.ElmTr2")):
            lado = "bushv" if r.GetClassName() == "ElmTr2" else "bus1"
            modelo["resultados_flujo"]["ramas"][r.loc_name] = {
                "cargabilidad_pct": attr(r, "c:loading"),
                "p_MW": attr(r, "m:P:" + lado), "q_Mvar": attr(r, "m:Q:" + lado),
                "i_kA": attr(r, "m:I:" + lado), "perdidas_kW": attr(r, "c:Ploss"),
            }

    with open(salida, "w", encoding="utf-8") as f:
        json.dump(modelo, f, ensure_ascii=False, indent=2, default=str)

    app.PrintPlain("Modelo neutro exportado a: " + salida)
    app.PrintPlain("Barras: %d | Lineas: %d | Trafos: %d | Cargas: %d | Graficos: %d" % (
        len(modelo["barras"]), len(modelo["lineas"]), len(modelo["transformadores"]),
        len(modelo["cargas"]), len(modelo["graficos"])))
    return modelo


if __name__ == "__main__":
    exportar(powerfactory.GetApplication())
