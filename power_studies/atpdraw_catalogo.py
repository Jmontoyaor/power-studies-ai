"""Catálogo de componentes de ATPDraw aprendido de proyectos reales.

Cada proyecto de ATPDraw guardado como XML (File > Save As > XML text format, ATPDraw
>= 7.0) trae la definición exacta de sus componentes: nodos, fases, posición relativa
de los terminales, nombres y unidades de los datos, y estructuras extra (curvas no
lineales, sondas, LCC...). `construir` recorre una carpeta de esos XML y guarda una
plantilla por componente en `adaptadores/atpdraw_catalogo.json`. El adaptador de
ATPDraw la usa para colocar cualquier componente sin investigar su formato.

Para ampliar el catálogo con proyectos nuevos (los ejemplos de ATPDraw o proyectos
propios), guárdelos como XML en una carpeta y ejecute:

    power-studies atpdraw-catalogo --construir carpeta_con_xml

El catálogo describe el FORMATO; el uso eléctrico correcto de cada componente (qué
modelo elegir y cómo parametrizarlo) se valida aparte, como el resto del proyecto.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

RUTA = Path(__file__).parent / "adaptadores" / "atpdraw_catalogo.json"
INDICE = Path(__file__).parent / "adaptadores" / "atpdraw_catalogo_indice.json"
CARPETA_REPO = Path(__file__).resolve().parents[1] / "atpdraw" / "proyectos_xml"
MAX_EJEMPLOS = 5


def _limpiar(comp: ET.Element) -> ET.Element:
    """Plantilla neutra: sin posición ni nombres de nodo del proyecto de origen."""
    c = copy.deepcopy(comp)
    cc = c.find("comp_content")
    for a in ("PosX", "PosY", "Angle"):
        cc.attrib.pop(a, None)
    for n in cc.iter("node"):
        n.set("Value", "")
        for a in ("UserNamed", "Ground"):
            n.attrib.pop(a, None)
    return c


def construir(carpeta: str | Path, destino: str | Path = RUTA, anterior: dict | None = None) -> dict:
    """Lee todos los *.xml de `carpeta` y escribe el catálogo JSON (fusiona con `anterior`)."""
    cat = anterior or {"version": 1, "componentes": {}}
    comps = cat["componentes"]
    for xml in sorted(Path(carpeta).glob("*.xml")):
        try:
            raiz = ET.parse(xml).getroot()
        except ET.ParseError:
            continue
        if raiz.tag != "project":
            continue
        proyecto = xml.stem
        for comp in raiz.iter("comp"):
            nombre = comp.get("Name")
            cc = comp.find("comp_content")
            if not nombre or cc is None:
                continue
            e = comps.setdefault(nombre, {"plantilla": ET.tostring(_limpiar(comp), encoding="unicode"),
                                          "nodos": [], "datos": [], "proyectos": [], "veces": 0})
            if not e["nodos"]:
                e["nodos"] = [{"nombre": n.get("Name"), "fases": int(n.get("NumPhases", 1)),
                               "kind": int(n.get("Kind", 1)), "dx": int(n.get("PosX", 0)), "dy": int(n.get("PosY", 0)),
                               "deshabilitado": n.get("Disabled") == "true", "interno": n.get("Internal") == "true"}
                              for n in cc.iter("node")]
                e["datos"] = [{"nombre": d.get("Name"), "unidad": d.get("Unit", ""), "ejemplos": []}
                              for d in cc.iter("data")]
            for i, d in enumerate(cc.iter("data")):
                if i < len(e["datos"]) and d.get("Value") not in e["datos"][i]["ejemplos"] \
                        and len(e["datos"][i]["ejemplos"]) < MAX_EJEMPLOS:
                    e["datos"][i]["ejemplos"].append(d.get("Value"))
            e["veces"] += 1
            if proyecto not in e["proyectos"]:
                e["proyectos"].append(proyecto)
    cat["componentes"] = dict(sorted(comps.items()))
    Path(destino).write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    return cat


def cargar(ruta: str | Path = RUTA) -> dict:
    if not Path(ruta).exists():
        raise FileNotFoundError(f"no hay catálogo en {ruta}: ejecute power-studies atpdraw-catalogo --construir")
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def componente(nombre: str, x: int, y: int, nodos: dict[str, str] | None = None,
               datos: dict[str, object] | None = None, tierra: set[str] | frozenset = frozenset(),
               angulo: int | None = None, catalogo: dict | None = None) -> ET.Element:
    """Instancia un componente del catálogo en (x, y).

    nodos: nombre del terminal -> nombre del nodo (queda con UserNamed="true").
    datos: nombre del dato -> valor; si el nombre se repite en el componente, pase una
           lista con un valor por aparición.
    tierra: terminales que van a tierra (Ground="1")."""
    cat = catalogo or cargar()
    if nombre not in cat["componentes"]:
        raise KeyError(f"'{nombre}' no está en el catálogo de ATPDraw ({len(cat['componentes'])} componentes)")
    comp = ET.fromstring(cat["componentes"][nombre]["plantilla"])
    cc = comp.find("comp_content")
    cc.set("PosX", str(x))
    cc.set("PosY", str(y))
    if angulo is not None:
        cc.set("Angle", str(angulo))
    terminales = {n.get("Name"): n for n in cc.iter("node")}
    for t, v in (nodos or {}).items():
        if t not in terminales:
            raise KeyError(f"{nombre} no tiene el terminal '{t}'; terminales: {sorted(terminales)}")
        terminales[t].set("Value", v)
        terminales[t].set("UserNamed", "true")
    for t in tierra:
        if t not in terminales:
            raise KeyError(f"{nombre} no tiene el terminal '{t}'; terminales: {sorted(terminales)}")
        terminales[t].set("Ground", "1")
    elementos = list(cc.iter("data"))
    validos = {d.get("Name") for d in elementos}
    for dn, valor in (datos or {}).items():
        if dn not in validos:
            raise KeyError(f"{nombre} no tiene el dato '{dn}'; datos: {sorted(validos)}")
        apariciones = [d for d in elementos if d.get("Name") == dn]
        valores = valor if isinstance(valor, (list, tuple)) else [valor]
        for d, v in zip(apariciones, valores):
            d.set("Value", str(v))
    return comp


def describir(nombre: str, catalogo: dict | None = None) -> str:
    """Ficha legible de un componente: terminales, datos con unidades y ejemplos."""
    e = (catalogo or cargar())["componentes"][nombre]
    lineas = [f"{nombre}: visto {e['veces']} veces en {', '.join(e['proyectos'][:6])}"
              + (" ..." if len(e["proyectos"]) > 6 else "")]
    lineas.append("  Terminales:")
    for n in e["nodos"]:
        extra = "".join([" (deshabilitado)" if n["deshabilitado"] else "", " (interno)" if n["interno"] else ""])
        lineas.append(f"    {n['nombre']:12s} fases={n['fases']} posición=({n['dx']},{n['dy']}){extra}")
    lineas.append("  Datos:")
    for d in e["datos"]:
        lineas.append(f"    {d['nombre']:14s} [{d['unidad']}]  ejemplos: {', '.join(map(str, d['ejemplos']))}")
    return "\n".join(lineas)


def carpetas_de_proyectos() -> list[Path]:
    """Dónde buscar proyectos XML: atpdraw/proyectos_xml del repo y las carpetas de la
    variable de entorno POWER_STUDIES_ATPDRAW (separadas por ';' en Windows, ':' en Linux)."""
    carpetas = [CARPETA_REPO]
    extra = os.environ.get("POWER_STUDIES_ATPDRAW", "")
    carpetas += [Path(c) for c in extra.split(os.pathsep) if c.strip()]
    return [c for c in carpetas if c.is_dir()]


def retroalimentar(carpetas: list[Path] | None = None, ruta: Path = RUTA, indice: Path = INDICE) -> list[str]:
    """Aprende de los proyectos XML nuevos o modificados (por su huella SHA-256).

    Devuelve los nombres de los proyectos incorporados. Es incremental: un archivo ya
    procesado y sin cambios no se vuelve a leer."""
    vistos = json.loads(indice.read_text(encoding="utf-8")) if indice.exists() else {}
    nuevos = []
    for carpeta in carpetas if carpetas is not None else carpetas_de_proyectos():
        for xml in sorted(Path(carpeta).glob("*.xml")):
            huella = hashlib.sha256(xml.read_bytes()).hexdigest()
            if vistos.get(xml.name) == huella:
                continue
            try:
                if ET.parse(xml).getroot().tag != "project":
                    continue
            except ET.ParseError:
                continue
            nuevos.append(xml)
            vistos[xml.name] = huella
    if not nuevos:
        return []
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for xml in nuevos:
            shutil.copy(xml, Path(tmp) / xml.name)
        antes = set(cargar(ruta)["componentes"]) if ruta.exists() else set()
        cat = construir(tmp, ruta, cargar(ruta) if ruta.exists() else None)
    indice.write_text(json.dumps(dict(sorted(vistos.items())), indent=1), encoding="utf-8")
    aprendidos = sorted(set(cat["componentes"]) - antes)
    print(f"[catálogo ATPDraw] {len(nuevos)} proyecto(s) nuevo(s): {', '.join(x.stem for x in nuevos)}"
          + (f"; componentes nuevos: {', '.join(aprendidos)}" if aprendidos else ""))
    return [x.stem for x in nuevos]
