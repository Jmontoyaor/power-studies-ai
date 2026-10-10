"""Catálogo de componentes de ATPDraw aprendido de proyectos reales (XML de ATPDraw 7.8)."""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from power_studies.adaptadores.atpdraw_ad import generar_xml
from power_studies.atpdraw_catalogo import cargar, componente, construir, describir
from power_studies.modelo import Red

CASOS = Path(__file__).resolve().parents[1] / "casos"
CAT = cargar()


def test_catalogo_tiene_los_componentes_principales():
    for nombre in ("RESISTOR", "RLC3", "RLCY3", "LCC", "HEIDLER", "SATTRAFO", "BCTRAN3", "ACSOURCE",
                   "LINEPI3S", "LINERL3S", "PROBE_V", "SW_TACS", "MOVN", "TRAFO_I3"):
        assert nombre in CAT["componentes"], nombre


@pytest.mark.parametrize("caso,opciones", [
    ("subestacion_75kva", {}), ("subestacion_75kva", {"falla": "BT", "tipo_falla": "1f"}),
    ("ejemplo_4_barras", {"falla": "B4", "tipo_falla": "2f"})])
def test_el_adaptador_escribe_el_formato_real_de_atpdraw(caso, opciones):
    """Los componentes que el adaptador arma a mano tienen los mismos terminales y datos
    (en el mismo orden) que los que ATPDraw guarda en sus proyectos."""
    raiz = ET.fromstring(generar_xml(Red.cargar(CASOS / caso / "red.yaml"), **opciones))
    for comp in raiz.iter("comp"):
        ref = CAT["componentes"][comp.get("Name")]
        cc = comp.find("comp_content")
        assert [n.get("Name") for n in cc.iter("node")] == [n["nombre"] for n in ref["nodos"]], comp.get("Name")
        datos = [d.get("Name") for d in cc.iter("data")]
        esperados = [d["nombre"] for d in ref["datos"]]
        if comp.get("Name") == "SATTRAFO":   # algunos proyectos repiten "I0" donde otros dicen "F0"
            esperados = ["F0" if i == 1 else n for i, n in enumerate(esperados)]
        assert datos == esperados, comp.get("Name")


def test_componente_desde_el_catalogo():
    c = componente("HEIDLER", 2800, 2700, nodos={"HEI": "TOPE"},
                   datos={"Amplitude": 31000, "T_f": 1.2e-6, "tau": 5e-5}, catalogo=CAT)
    cc = c.find("comp_content")
    assert (cc.get("PosX"), cc.get("PosY")) == ("2800", "2700")
    nodo = cc.find("node[@Name='HEI']")
    assert nodo.get("Value") == "TOPE" and nodo.get("UserNamed") == "true"
    assert cc.find("data[@Name='Amplitude']").get("Value") == "31000"


def test_componente_avisa_datos_y_terminales_invalidos():
    with pytest.raises(KeyError, match="no tiene el dato"):
        componente("RESISTOR", 0, 0, datos={"OHMS": 1}, catalogo=CAT)
    with pytest.raises(KeyError, match="no tiene el terminal"):
        componente("RESISTOR", 0, 0, nodos={"X": "A"}, catalogo=CAT)
    with pytest.raises(KeyError, match="no está en el catálogo"):
        componente("NO_EXISTE", 0, 0, catalogo=CAT)


def test_datos_repetidos_por_aparicion():
    c = componente("ACSOURCE", 0, 0, datos={"StopA": [1, 2, 3]}, catalogo=CAT)
    assert [d.get("Value") for d in c.iter("data") if d.get("Name") == "StopA"] == ["1", "2", "3"]


def test_tierra_y_ficha(tmp_path):
    c = componente("RLCY3", 0, 0, nodos={"IN": "B1"}, tierra={"OUT"}, catalogo=CAT)
    assert c.find("comp_content/node[@Name='OUT']").get("Ground") == "1"
    assert "Terminales" in describir("LCC", CAT)


def test_construir_desde_un_proyecto(tmp_path):
    xml = ('<project Application="ATPDraw"><objects><comp Name="RESISTOR"><comp_content PosX="10" PosY="20">'
           '<node Name="From" Value="A" UserNamed="true" Kind="1" PosX="-20" PosY="0"/>'
           '<node Name="To" Value="" Kind="1" PosX="20" PosY="0" Ground="1"/>'
           '<data Name="RES" Unit="Ohms" Value="5"/></comp_content></comp></objects></project>')
    (tmp_path / "p.xml").write_text(xml)
    c = construir(tmp_path, tmp_path / "cat.json")
    r = c["componentes"]["RESISTOR"]
    assert r["veces"] == 1 and r["datos"][0]["ejemplos"] == ["5"]
    plantilla = ET.fromstring(r["plantilla"]).find("comp_content")
    assert "PosX" not in plantilla.attrib and all(n.get("Value") == "" for n in plantilla.iter("node"))


def test_retroalimentacion_incremental(tmp_path):
    """Los proyectos nuevos se incorporan solos; los ya vistos y sin cambios no se releen."""
    import shutil

    from power_studies.atpdraw_catalogo import RUTA, retroalimentar
    cat, ind, carpeta = tmp_path / "cat.json", tmp_path / "ind.json", tmp_path / "proyectos"
    carpeta.mkdir()
    shutil.copy(RUTA, cat)
    proyecto = ('<project Application="ATPDraw"><objects><comp Name="COMPONENTE_NUEVO"><comp_content PosX="0" PosY="0">'
                '<node Name="A" Value="" Kind="1" PosX="-20" PosY="0"/><data Name="X" Unit="" Value="{v}"/>'
                '</comp_content></comp></objects></project>')
    (carpeta / "mio.xml").write_text(proyecto.format(v=1))
    (carpeta / "otro.xml").write_text("<no_es_atpdraw/>")
    assert retroalimentar([carpeta], cat, ind) == ["mio"]
    assert "COMPONENTE_NUEVO" in cargar(cat)["componentes"]
    assert retroalimentar([carpeta], cat, ind) == []            # sin cambios: no se relee
    (carpeta / "mio.xml").write_text(proyecto.format(v=2))
    assert retroalimentar([carpeta], cat, ind) == ["mio"]       # cambió: se vuelve a aprender
    assert cargar(cat)["componentes"]["COMPONENTE_NUEVO"]["datos"][0]["ejemplos"] == ["1", "2"]
