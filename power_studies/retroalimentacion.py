"""Retroalimentación: el proyecto aprende de los archivos reales de cada programa.

Deje archivos en `retroalimentacion/<programa>/` (o en las mismas subcarpetas bajo la ruta
de la variable de entorno POWER_STUDIES_RETRO). Cada vez que se ejecuta `power-studies`,
los archivos nuevos o modificados (por huella SHA-256) se procesan y su conocimiento se
guarda en `power_studies/conocimiento/<programa>.json`, consultable con
`power-studies conocimiento`.

| Programa     | Archivos              | Qué se aprende                                                   |
|--------------|-----------------------|------------------------------------------------------------------|
| atpdraw      | .xml (Save As XML)    | plantilla de cada componente (catálogo que usa el adaptador)     |
| opendss      | .dss                  | clases de elementos, propiedades y valores típicos               |
| autocad      | .dxf                  | capas, bloques (símbolos) con atributos, estilos y unidades      |
| powerfactory | .dgs .csv .xlsx       | tablas y columnas de los exportes                                |
| etap         | .xlsx .csv            | hojas y columnas de las plantillas de importación de su versión  |
| pvsyst       | .pan .ond .csv        | parámetros de módulos e inversores; columnas de exportes         |

Lo aprendido describe FORMATOS y valores de referencia. Usarlo en un cálculo exige la
misma validación que el resto del proyecto (AGENTS.md).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "retroalimentacion"
CONOCIMIENTO = Path(__file__).parent / "conocimiento"
INDICE = CONOCIMIENTO / "_indice.json"
MAX_EJEMPLOS = 5


def _ejemplo(lista: list, valor) -> None:
    v = str(valor)
    if v not in lista and len(lista) < MAX_EJEMPLOS:
        lista.append(v)


def _fuente(entrada: dict, archivo: str) -> None:
    entrada["veces"] = entrada.get("veces", 0) + 1
    fuentes = entrada.setdefault("archivos", [])
    if archivo not in fuentes:
        fuentes.append(archivo)


# ------------------------------------------------------------------ aprendices
def aprender_atpdraw(ruta: Path, k: dict) -> list[str]:
    """Delegado al catálogo de ATPDraw (lo usa el adaptador para dibujar)."""
    import shutil
    import tempfile

    from . import atpdraw_catalogo as cat
    antes = set(cat.cargar()["componentes"]) if cat.RUTA.exists() else set()
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(ruta, Path(tmp) / ruta.name)
        nuevo = cat.construir(tmp, cat.RUTA, cat.cargar() if cat.RUTA.exists() else None)
    k["componentes"] = len(nuevo["componentes"])
    return sorted(set(nuevo["componentes"]) - antes)


_DSS_NEW = re.compile(r"^\s*new\s+(?:object\s*=\s*)?([A-Za-z]+)\.(\S+)\s*(.*)$", re.I)
_DSS_PROP = re.compile(r'([A-Za-z0-9_%]+)\s*=\s*("[^"]*"|\([^)]*\)|\[[^\]]*\]|\'[^\']*\'|\S+)')


def aprender_opendss(ruta: Path, k: dict) -> list[str]:
    """Elementos `New Clase.nombre prop=valor` (con continuaciones `~`)."""
    clases = k.setdefault("clases", {})
    nuevos = []
    actual = None
    for linea in ruta.read_text(encoding="utf-8", errors="ignore").splitlines():
        linea = re.split(r"!|//", linea, maxsplit=1)[0].strip()
        if not linea:
            continue
        m = _DSS_NEW.match(linea)
        if m:
            clase = m.group(1).capitalize()
            if clase not in clases:
                nuevos.append(clase)
            actual = clases.setdefault(clase, {"propiedades": {}})
            _fuente(actual, ruta.name)
            resto = m.group(3)
        elif linea.startswith("~") and actual is not None:
            resto = linea[1:]
        else:
            actual = None if not linea.startswith("~") else actual
            continue
        for prop, valor in _DSS_PROP.findall(resto):
            _ejemplo(actual["propiedades"].setdefault(prop.lower(), []), valor.strip("\"'"))
    return nuevos


def aprender_autocad(ruta: Path, k: dict) -> list[str]:
    """Capas, bloques con atributos, estilos de texto y unidades de un DXF."""
    import ezdxf
    doc = ezdxf.readfile(ruta)
    nuevos = []
    capas = k.setdefault("capas", {})
    for capa in doc.layers:
        n = capa.dxf.name
        if n not in capas:
            nuevos.append(f"capa {n}")
        e = capas.setdefault(n, {"color": capa.dxf.color, "tipo_linea": capa.dxf.linetype})
        _fuente(e, ruta.name)
    bloques = k.setdefault("bloques", {})
    for b in doc.blocks:
        if b.name.startswith("*"):  # bloques anónimos y de espacio de papel/modelo
            continue
        tipos: dict[str, int] = {}
        for ent in b:
            tipos[ent.dxftype()] = tipos.get(ent.dxftype(), 0) + 1
        if b.name not in bloques:
            nuevos.append(f"bloque {b.name}")
        e = bloques.setdefault(b.name, {"entidades": tipos,
                                        "atributos": [a.dxf.tag for a in b.query("ATTDEF")]})
        _fuente(e, ruta.name)
    estilos = k.setdefault("estilos_texto", {})
    for st in doc.styles:
        estilos.setdefault(st.dxf.name, {"fuente": st.dxf.font})
    _ejemplo(k.setdefault("unidades_insunits", []), doc.header.get("$INSUNITS", 0))
    return nuevos


_DGS_TABLA = re.compile(r"^\$\$([A-Za-z0-9_]+);(.*)$")


def _tablas(ruta: Path, k: dict) -> list[str]:
    """Encabezados de tablas: DGS de PowerFactory, CSV y hojas de Excel."""
    tablas = k.setdefault("tablas", {})
    nuevos = []

    def registrar(nombre: str, columnas: list[str], muestra: list | None):
        columnas = [c.strip() for c in columnas if c and c.strip()]
        if not columnas:
            return
        if nombre not in tablas:
            nuevos.append(nombre)
        e = tablas.setdefault(nombre, {"columnas": [], "muestra": []})
        for c in columnas:
            if c not in e["columnas"]:
                e["columnas"].append(c)
        if muestra and not e["muestra"]:
            e["muestra"] = [str(x) for x in muestra][:len(columnas)]
        _fuente(e, ruta.name)

    suf = ruta.suffix.lower()
    if suf == ".dgs":
        for linea in ruta.read_text(encoding="latin-1", errors="ignore").splitlines():
            m = _DGS_TABLA.match(linea.strip())
            if m:
                registrar(m.group(1), [re.sub(r"\(.*\)$", "", c) for c in m.group(2).split(";")], None)
    elif suf == ".csv":
        texto = ruta.read_text(encoding="utf-8", errors="ignore")
        try:
            dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel
        filas = list(csv.reader(texto.splitlines()[:2], dialecto))
        if filas:
            registrar(ruta.stem, filas[0], filas[1] if len(filas) > 1 else None)
    elif suf in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        for ws in wb.worksheets:
            filas = [f for f in ws.iter_rows(max_row=30, values_only=True) if any(c is not None for c in f)]
            if filas:
                registrar(f"{ruta.stem}/{ws.title}", [str(c) for c in filas[0] if c is not None],
                          filas[1] if len(filas) > 1 else None)
    return nuevos


def aprender_pvsyst(ruta: Path, k: dict) -> list[str]:
    """Archivos .PAN/.OND (texto `Clave=Valor`) y exportes tabulares."""
    if ruta.suffix.lower() not in (".pan", ".ond"):
        return _tablas(ruta, k)
    objetos = k.setdefault("objetos", {})
    tipo = "modulo" if ruta.suffix.lower() == ".pan" else "inversor"
    e = objetos.setdefault(tipo, {"parametros": {}})
    nuevos = []
    for linea in ruta.read_text(encoding="latin-1", errors="ignore").splitlines():
        if "=" not in linea:
            continue
        clave, valor = (x.strip() for x in linea.split("=", 1))
        if not clave or clave.startswith(("PVObject", "End of")):
            continue
        if clave not in e["parametros"]:
            nuevos.append(f"{tipo}.{clave}")
        _ejemplo(e["parametros"].setdefault(clave, []), valor)
    _fuente(e, ruta.name)
    return nuevos


APRENDICES = {
    "atpdraw": ((".xml",), aprender_atpdraw),
    "opendss": ((".dss",), aprender_opendss),
    "autocad": ((".dxf",), aprender_autocad),
    "powerfactory": ((".dgs", ".csv", ".xlsx"), _tablas),
    "etap": ((".xlsx", ".xlsm", ".csv"), _tablas),
    "pvsyst": ((".pan", ".ond", ".csv"), aprender_pvsyst),
}


# ------------------------------------------------------------------ motor
def carpetas(programa: str) -> list[Path]:
    """retroalimentacion/<programa>/ del repo y <POWER_STUDIES_RETRO>/<programa>/."""
    raices = [CARPETA] + [Path(r) for r in os.environ.get("POWER_STUDIES_RETRO", "").split(os.pathsep) if r.strip()]
    out = [r / programa for r in raices if (r / programa).is_dir()]
    if programa == "atpdraw":
        legado = RAIZ / "atpdraw" / "proyectos_xml"  # ubicación anterior
        out += [legado] if legado.is_dir() else []
        out += [Path(c) for c in os.environ.get("POWER_STUDIES_ATPDRAW", "").split(os.pathsep) if c.strip()]
    return out


def cargar(programa: str, base: Path = CONOCIMIENTO) -> dict:
    ruta = base / f"{programa}.json"
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}


def retroalimentar(programas: list[str] | None = None, base: Path = CONOCIMIENTO,
                   origen: dict[str, list[Path]] | None = None, silencio: bool = False) -> dict[str, list[str]]:
    """Procesa los archivos nuevos o modificados de cada programa.

    Devuelve {programa: [lo aprendido]} solo para los programas con archivos nuevos.
    `origen` reemplaza las carpetas (para pruebas)."""
    base.mkdir(parents=True, exist_ok=True)
    indice_ruta = base / "_indice.json"
    indice = json.loads(indice_ruta.read_text(encoding="utf-8")) if indice_ruta.exists() else {}
    resultado: dict[str, list[str]] = {}
    for programa in programas or list(APRENDICES):
        extensiones, aprender = APRENDICES[programa]
        vistos = indice.setdefault(programa, {})
        k = cargar(programa, base)
        aprendido: list[str] = []
        procesados = 0
        lista = origen.get(programa, []) if origen is not None else carpetas(programa)
        for carpeta in lista:
            for archivo in sorted(Path(carpeta).iterdir()):
                if archivo.suffix.lower() not in extensiones or not archivo.is_file():
                    continue
                huella = hashlib.sha256(archivo.read_bytes()).hexdigest()
                if vistos.get(archivo.name) == huella:
                    continue
                try:
                    aprendido += aprender(archivo, k)
                except Exception as e:  # un archivo dañado no detiene al resto
                    aprendido.append(f"(no se pudo leer {archivo.name}: {e})")
                vistos[archivo.name] = huella
                procesados += 1
        if procesados:
            k.setdefault("archivos_procesados", 0)
            k["archivos_procesados"] += procesados
            (base / f"{programa}.json").write_text(json.dumps(k, ensure_ascii=False, indent=1), encoding="utf-8")
            resultado[programa] = aprendido
            if not silencio:
                muestra = ", ".join(aprendido[:8]) + (" ..." if len(aprendido) > 8 else "")
                print(f"[retroalimentación] {programa}: {procesados} archivo(s) nuevo(s)"
                      + (f"; aprendió {len(aprendido)}: {muestra}" if aprendido else ""))
    indice_ruta.write_text(json.dumps(indice, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return resultado


def resumen(base: Path = CONOCIMIENTO) -> dict[str, str]:
    """Una línea por programa con lo que se sabe de él."""
    out = {}
    for programa in APRENDICES:
        k = cargar(programa, base)
        if programa == "atpdraw":
            from . import atpdraw_catalogo as cat
            n = len(cat.cargar()["componentes"]) if cat.RUTA.exists() else 0
            out[programa] = f"{n} componentes en el catálogo"
        elif programa == "opendss":
            out[programa] = f"{len(k.get('clases', {}))} clases de elementos"
        elif programa == "autocad":
            out[programa] = f"{len(k.get('capas', {}))} capas, {len(k.get('bloques', {}))} bloques"
        elif programa == "pvsyst":
            out[programa] = (f"{sum(len(o['parametros']) for o in k.get('objetos', {}).values())} parámetros de "
                             f"módulos/inversores, {len(k.get('tablas', {}))} tablas")
        else:
            out[programa] = f"{len(k.get('tablas', {}))} tablas"
        out[programa] += f" ({k.get('archivos_procesados', 0)} archivos procesados)"
    return out
