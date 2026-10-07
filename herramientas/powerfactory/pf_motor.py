# -*- coding: utf-8 -*-
"""
pf_motor.py - Corre PowerFactory SIN abrir la interfaz (modo motor / engine mode).

Permite que un agente (Claude Code, OpenCode...) que corre en el mismo
Windows donde está PowerFactory ejecute el flujo completo sin clics:

    python pf_motor.py --proyecto "subestaciones 75 kva" --modelo modelo.json
    python pf_motor.py --proyecto "subestaciones 75 kva" --exportar   # PF -> modelo neutro

Requisitos: licencia con acceso Python externo y la versión de Python que
corresponde a su PowerFactory (ver Ayuda > Acerca de / manual, cap. Python).
"""
import argparse
import glob
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))


def ruta_python_pf():
    """Busca la carpeta Python de la instalación más reciente de PowerFactory."""
    if os.environ.get("PF_PYTHON"):
        return os.environ["PF_PYTHON"]
    candidatos = sorted(glob.glob(r"C:\Program Files\DIgSILENT\PowerFactory*\Python\3.*"))
    if not candidatos:
        sys.exit("No encontré PowerFactory. Defina la variable PF_PYTHON con la carpeta "
                 r"...\PowerFactory 20xx\Python\3.x")
    return candidatos[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proyecto", required=True, help="Nombre del proyecto en la base de datos")
    ap.add_argument("--caso", help="Caso de estudio a activar")
    ap.add_argument("--modelo", help="Modelo neutro JSON a construir")
    ap.add_argument("--resultados", default="resultados_powerfactory.json")
    ap.add_argument("--exportar", action="store_true", help="Exportar el proyecto a modelo neutro")
    ap.add_argument("--usuario", help="Usuario de PowerFactory (si aplica)")
    a = ap.parse_args()

    sys.path.append(ruta_python_pf())
    sys.path.append(AQUI)
    import powerfactory  # noqa: E402

    app = powerfactory.GetApplicationExt(a.usuario) if a.usuario else powerfactory.GetApplicationExt()
    if app.ActivateProject(a.proyecto):
        sys.exit("No se pudo activar el proyecto '%s'" % a.proyecto)
    if a.caso:
        casos = app.GetProjectFolder("study").GetContents(a.caso + ".IntCase", 1)
        if not casos:
            sys.exit("Caso de estudio '%s' no encontrado" % a.caso)
        casos[0].Activate()

    if a.exportar:
        import pf_exportar_modelo
        pf_exportar_modelo.exportar(app, os.path.abspath("modelo_exportado_pf.json"))
        return
    if not a.modelo:
        sys.exit("Indique --modelo o --exportar")
    import pf_construir_red
    pf_construir_red.DIBUJAR = True
    res = pf_construir_red.main(app, os.path.abspath(a.modelo), os.path.abspath(a.resultados))
    print("Convergió:", res["convergio"])


if __name__ == "__main__":
    main()
