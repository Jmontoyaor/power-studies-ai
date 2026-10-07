"""CLI `power-studies`. Es la interfaz que usan los agentes (y usted).

    power-studies herramientas
    power-studies nuevo estudios/mi-estudio --desde casos/subestacion_75kva/red.yaml
    power-studies validar red.yaml
    power-studies simular red.yaml --herramienta pandapower --escenario todos --cortocircuito
    power-studies comparar red.yaml --herramientas pandapower,opendss
    power-studies unifilar red.yaml --resultados res.json --salida unifilar
    power-studies informe red.yaml --salida informe.docx --cruce opendss
    power-studies exportar red.yaml --herramienta powerfactory --salida pf/
    power-studies importar-pf modelo_neutro_75kva.json --salida red.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import warnings
from pathlib import Path

os.environ.setdefault("NUMBA_DISABLE_JIT", "1")
warnings.filterwarnings("ignore")


def _red(ruta):
    from .modelo import Red
    return Red.cargar(ruta)


def _escenarios(red, arg):
    if arg in (None, "todos"):
        return [e.id for e in red.escenarios] if arg == "todos" else [red.escenarios[0].id]
    return arg.split(",")


def cmd_herramientas(a):
    from .adaptadores import REGISTRO
    for nombre, cls in REGISTRO.items():
        ok, motivo = cls().disponible()
        print(f"{nombre:13s} {'disponible' if ok else 'no disponible':14s} "
              f"capacidades={','.join(cls.capacidades):35s} {'' if ok else motivo}")


def cmd_nuevo(a):
    raiz = Path(a.carpeta)
    for sub in ("insumos", "modelo", "resultados", "informe", "herramientas"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    if a.desde:
        shutil.copy(a.desde, raiz / "modelo" / "red.yaml")
    estado = raiz / "ESTADO.md"
    if not estado.exists():
        estado.write_text(
            f"# Estado del estudio\n\n| Fase | Estado | Nota |\n|---|---|---|\n"
            f"| 0 Insumos | pendiente | |\n| 1 Modelo | {'borrador' if a.desde else 'pendiente'} | |\n"
            "| 2 Simulación | pendiente | |\n| 3 Verificación | pendiente | |\n"
            "| 4 Herramientas externas | pendiente | |\n| 5 Informe | pendiente | |\n",
            encoding="utf-8")
    print(f"Estudio creado en {raiz}")


def cmd_validar(a):
    red = _red(a.red)
    print(f"Modelo válido: {red.proyecto} | {len(red.barras)} barras, {len(red.lineas)} líneas, "
          f"{len(red.transformadores)} trafos, {len(red.cargas)} cargas, {len(red.generadores_pv)} FV")
    sup = red.supuestos()
    if sup:
        print(f"\n{len(sup)} datos por confirmar:")
        for s in sup:
            print("  -", s)


def cmd_simular(a):
    from .adaptadores import obtener
    from .validacion import contra_referencia
    red = _red(a.red)
    ad = obtener(a.herramienta)
    sal = Path(a.salida)
    sal.mkdir(parents=True, exist_ok=True)
    codigo = 0
    for esc in _escenarios(red, a.escenario):
        res = ad.flujo(red, esc)
        if a.cortocircuito and "cortocircuito" in ad.capacidades:
            res.cortocircuito = ad.cortocircuito(red, esc).cortocircuito
        ruta = sal / f"resultados_{ad.nombre}_{esc}.json"
        res.guardar(ruta)
        print(f"[{esc}] convergió={res.convergio} iter={res.iteraciones} -> {ruta}")
        for bid, rb in res.barras.items():
            print(f"    {bid:10s} {rb.u_pu:.4f} p.u. {rb.angulo_deg:8.2f}°")
        for rid, rr in res.ramas.items():
            print(f"    {rid:10s} {rr.cargabilidad_pct:6.1f} %  {rr.p_MW * 1000:8.2f} kW")
        ok, det = contra_referencia(red, res)
        for d in det:
            print("    ref:", d)
        if not ok:
            codigo = 2
    sys.exit(codigo)


def cmd_comparar(a):
    from .adaptadores import obtener
    from .resultados import comparar
    red = _red(a.red)
    hs = a.herramientas.split(",")
    malo = False
    for esc in _escenarios(red, a.escenario):
        rs = [obtener(h).flujo(red, esc) for h in hs]
        for r in rs[1:]:
            dif = comparar(rs[0], r, a.tol_u, a.tol_carga)
            print(f"[{esc}] {rs[0].herramienta} vs {r.herramienta}: "
                  + ("coinciden" if not dif else f"{len(dif)} diferencias"))
            for d in dif:
                print("    ", d)
            malo |= bool(dif)
    sys.exit(2 if malo else 0)


def cmd_verificar(a):
    from .normas import verificar
    from .resultados import Resultados
    red = _red(a.red)
    res = Resultados.cargar(a.resultados)
    vs = verificar(red, res)
    for v in vs:
        print(f"{v.estado.upper():10s} {v.criterio:40s} {v.elemento:35s} {v.valor:>8} {v.unidad} ({v.limite})")
    if a.json:
        Path(a.json).write_text(json.dumps([v.model_dump() for v in vs], ensure_ascii=False, indent=2),
                                encoding="utf-8")


def cmd_unifilar(a):
    from .diagrama import auto_layout, dibujar
    from .resultados import Resultados
    red = _red(a.red)
    res = Resultados.cargar(a.resultados) if a.resultados else None
    for r in dibujar(red, res, a.salida):
        print(r)
    if a.guardar_posiciones:
        auto_layout(red)
        red.guardar(a.red)
        print("posiciones guardadas en", a.red)


def cmd_informe(a):
    import yaml

    from .adaptadores import obtener
    from .informe import generar
    red = _red(a.red)
    ad = obtener(a.herramienta)
    resultados = {}
    for esc in _escenarios(red, a.escenario or "todos"):
        r = ad.flujo(red, esc)
        if a.cortocircuito and "cortocircuito" in ad.capacidades:
            r.cortocircuito = ad.cortocircuito(red, esc).cortocircuito
        resultados[esc] = r
    cruces = []
    for h in (a.cruce or "").split(","):
        if h:
            for esc, r in resultados.items():
                cruces.append((r, obtener(h).flujo(red, esc)))
    textos = yaml.safe_load(Path(a.textos).read_text(encoding="utf-8")) if a.textos else None
    print(generar(red, resultados, a.salida, cruces, textos))


def cmd_exportar(a):
    from .adaptadores import obtener
    red = _red(a.red)
    ad = obtener(a.herramienta)
    kw = {"plantilla": Path(a.plantilla)} if a.plantilla else {}
    for r in ad.exportar(red, Path(a.salida), a.escenario, **kw):
        print(r)


def cmd_importar_pf(a):
    from .adaptadores.powerfactory_ad import desde_exportacion
    red = desde_exportacion(a.json)
    red.guardar(a.salida)
    print(f"Modelo neutro escrito en {a.salida}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="power-studies", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)

    s.add_parser("herramientas").set_defaults(f=cmd_herramientas)

    q = s.add_parser("nuevo"); q.add_argument("carpeta"); q.add_argument("--desde")
    q.set_defaults(f=cmd_nuevo)

    q = s.add_parser("validar"); q.add_argument("red"); q.set_defaults(f=cmd_validar)

    q = s.add_parser("simular"); q.add_argument("red")
    q.add_argument("--herramienta", default="pandapower"); q.add_argument("--escenario")
    q.add_argument("--cortocircuito", action="store_true"); q.add_argument("--salida", default="resultados")
    q.set_defaults(f=cmd_simular)

    q = s.add_parser("comparar"); q.add_argument("red")
    q.add_argument("--herramientas", default="pandapower,opendss"); q.add_argument("--escenario", default="todos")
    q.add_argument("--tol-u", type=float, default=0.005); q.add_argument("--tol-carga", type=float, default=2.0)
    q.set_defaults(f=cmd_comparar)

    q = s.add_parser("verificar"); q.add_argument("red"); q.add_argument("--resultados", required=True)
    q.add_argument("--json"); q.set_defaults(f=cmd_verificar)

    q = s.add_parser("unifilar"); q.add_argument("red"); q.add_argument("--resultados")
    q.add_argument("--salida", default="unifilar"); q.add_argument("--guardar-posiciones", action="store_true")
    q.set_defaults(f=cmd_unifilar)

    q = s.add_parser("informe"); q.add_argument("red"); q.add_argument("--salida", default="informe.docx")
    q.add_argument("--herramienta", default="pandapower"); q.add_argument("--escenario")
    q.add_argument("--cruce", help="herramientas para validación cruzada, p. ej. opendss")
    q.add_argument("--cortocircuito", action="store_true")
    q.add_argument("--textos", help="YAML con introduccion/analisis/conclusiones del agente redactor")
    q.set_defaults(f=cmd_informe)

    q = s.add_parser("exportar"); q.add_argument("red"); q.add_argument("--herramienta", required=True)
    q.add_argument("--salida", required=True); q.add_argument("--escenario"); q.add_argument("--plantilla")
    q.set_defaults(f=cmd_exportar)

    q = s.add_parser("importar-pf"); q.add_argument("json"); q.add_argument("--salida", default="red.yaml")
    q.set_defaults(f=cmd_importar_pf)

    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
