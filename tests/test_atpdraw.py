"""Adaptador ATPDraw: el XML generado debe ser un circuito conectado por geometría
y la lectura del .lis de ATP debe reproducir el caso de 4 barras.

`datos/atp_4barras_E1_cargas_calibradas.lis` es la salida REAL de ATP (tpbigm,
corrido desde ATPDraw 7.8) para el XML de este adaptador, con las cargas como
impedancia constante calculada a la tensión de operación de pandapower.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from power_studies.adaptadores import obtener
from power_studies.adaptadores.atpdraw_ad import generar_xml, leer_lis
from power_studies.adaptadores.plantillas_ad import variables
from power_studies.modelo import Red

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "casos" / "ejemplo_4_barras" / "red.yaml"
SUB75 = RAIZ / "casos" / "subestacion_75kva" / "red.yaml"
LIS = Path(__file__).parent / "datos" / "atp_4barras_E1_cargas_calibradas.lis"


@pytest.fixture
def ejemplo():
    return Red.cargar(EJEMPLO)


def _terminales_y_cables(xml: str):
    raiz = ET.fromstring(xml)
    terminales, a_tierra = [], []
    for comp in raiz.iter("comp"):
        cc = comp.find("comp_content")
        x, y = int(cc.get("PosX")), int(cc.get("PosY"))
        for n in cc.iter("node"):
            if n.get("Disabled") == "true":
                continue
            p = (x + int(n.get("PosX")), y + int(n.get("PosY")))
            (a_tierra if n.get("Ground") == "1" else terminales).append((comp.get("Name"), n, p))
    cables = [((int(c.get("Pos1X")), int(c.get("Pos1Y"))), (int(c.get("Pos2X")), int(c.get("Pos2Y"))))
              for c in raiz.iter("conn_content")]
    return raiz, terminales, a_tierra, cables


@pytest.mark.parametrize("caso", [EJEMPLO, SUB75])
def test_xml_conectado_por_geometria(caso):
    red = Red.cargar(caso)
    _, terminales, _, cables = _terminales_y_cables(generar_xml(red))
    puntos_cable = [p for c in cables for p in c]
    posiciones = [p for _, _, p in terminales]
    for nombre, nodo, p in terminales:
        conectado = p in puntos_cable or posiciones.count(p) > 1
        assert conectado, f"{nombre}.{nodo.get('Name')} en {p} queda suelto"
    for p in puntos_cable:
        assert p in posiciones or puntos_cable.count(p) > 1, f"cable con extremo libre en {p}"
    for p in posiciones + puntos_cable:
        assert p[0] % 10 == 0 and p[1] % 10 == 0, f"{p} fuera de la grilla de ATPDraw"


@pytest.mark.parametrize("caso", [EJEMPLO, SUB75])
def test_nombres_de_nodo_validos_para_atp(caso):
    red = Red.cargar(caso)
    _, terminales, _, _ = _terminales_y_cables(generar_xml(red))
    for _, n, _ in terminales:
        v = n.get("Value")
        assert v and n.get("UserNamed") == "true"
        # ATP: 6 caracteres; ATPDraw agrega A/B/C a los nodos trifásicos.
        assert len(v) <= (5 if n.get("NumPhases") == "3" else 6)
    barras = {b.id.upper() for b in red.barras}
    assert barras <= {n.get("Value") for _, n, _ in terminales}


def test_parametros_iguales_al_modelo(ejemplo):
    raiz, _, _, _ = _terminales_y_cables(generar_xml(ejemplo, "E2"))
    var = variables(ejemplo, "E2")
    rlc = [c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == "RLC3"]
    r_lineas = sorted(float(cc.find("data[@Name='R_1']").get("Value")) for cc in rlc)
    esperado = sorted([float(var["LINEA_L_MT_R_OHM"]), float(var["LINEA_L_BT_R_OHM"]),
                       float(var["TRAFO_T1_R_BT_OHM"])])
    assert r_lineas == pytest.approx(esperado, rel=1e-5)
    trafo = next(c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == "TRAFO_I3")
    assert float(trafo.find("data[@Name='n']").get("Value")) == pytest.approx(13.2 / 0.22, rel=1e-6)
    fuente = next(c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == "ACSOURCE")
    assert float(fuente.find("data[@Name='AmplitudeA']").get("Value")) == pytest.approx(13200)


def test_tap_cambia_relacion(ejemplo):
    def relacion(esc):
        raiz = ET.fromstring(generar_xml(ejemplo, esc))
        t = next(c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == "TRAFO_I3")
        return float(t.find("data[@Name='n']").get("Value"))
    assert relacion("E3") == pytest.approx(relacion("E2") * (1 - 0.025), rel=1e-6)


def test_lis_de_atp_reproduce_el_caso_de_4_barras(ejemplo):
    u = leer_lis(LIS, ejemplo)
    ref = ejemplo.referencia["E1"]["u_pu"]
    for b, valor in ref.items():
        assert u[b][0] == pytest.approx(valor, abs=2e-4), b


def test_exportar_escribe_xml(ejemplo, tmp_path):
    rutas = obtener("atpdraw").exportar(ejemplo, tmp_path, "E1")
    assert rutas[0].name == "ejemplo_didactico_4_barras_E1.xml"
    raiz = ET.parse(rutas[0]).getroot()
    assert raiz.get("Application") == "ATPDraw"
