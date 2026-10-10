"""Adaptador ATPDraw: el XML generado debe ser un circuito conectado por geometría
y la lectura del .lis de ATP debe reproducir los casos de referencia.

Los archivos `datos/atp_*.lis` son salida REAL de ATP (tpbigm corrido desde
ATPDraw 7.8) para el XML de este adaptador. Las cargas de los casos de flujo son
impedancia constante calculada a la tensión de operación de pandapower.
"""
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from power_studies.adaptadores import obtener
from power_studies.adaptadores.atpdraw_ad import C_IEC, R_FALLA, generar_xml, leer_falla, leer_lis
from power_studies.adaptadores.plantillas_ad import variables
from power_studies.modelo import Red

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "casos" / "ejemplo_4_barras" / "red.yaml"
SUB75 = RAIZ / "casos" / "subestacion_75kva" / "red.yaml"
DATOS = Path(__file__).parent / "datos"


@pytest.fixture
def ejemplo():
    return Red.cargar(EJEMPLO)


@pytest.fixture
def sub75():
    return Red.cargar(SUB75)


def _comp(raiz, nombre):
    return [c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == nombre]


def _dato(cc, nombre):
    return float(cc.find(f"data[@Name='{nombre}']").get("Value"))


def _terminales_y_cables(xml: str):
    raiz = ET.fromstring(xml)
    terminales = []
    for comp in raiz.iter("comp"):
        cc = comp.find("comp_content")
        x, y = int(cc.get("PosX")), int(cc.get("PosY"))
        for n in cc.iter("node"):
            # Nodos deshabilitados, a tierra o internos (estrella del SATTRAFO) no se cablean.
            if n.get("Disabled") == "true" or n.get("Ground") == "1" or n.get("Kind") == "2":
                continue
            terminales.append((comp.get("Name"), n, (x + int(n.get("PosX")), y + int(n.get("PosY")))))
    cables = [((int(c.get("Pos1X")), int(c.get("Pos1Y"))), (int(c.get("Pos2X")), int(c.get("Pos2Y"))))
              for c in raiz.iter("conn_content")]
    return raiz, terminales, cables


CASOS_XML = [(EJEMPLO, {}), (SUB75, {}), (SUB75, {"falla_3f": "BT"}), (EJEMPLO, {"falla_3f": "B1"})]


@pytest.mark.parametrize("caso,opciones", CASOS_XML)
def test_xml_conectado_por_geometria(caso, opciones):
    red = Red.cargar(caso)
    _, terminales, cables = _terminales_y_cables(generar_xml(red, **opciones))
    puntos_cable = [p for c in cables for p in c]
    posiciones = [p for _, _, p in terminales]
    for nombre, nodo, p in terminales:
        assert p in puntos_cable or posiciones.count(p) > 1, f"{nombre}.{nodo.get('Name')} en {p} suelto"
    for p in puntos_cable:
        assert p in posiciones or puntos_cable.count(p) > 1, f"cable con extremo libre en {p}"
    for p in posiciones + puntos_cable:
        assert p[0] % 10 == 0 and p[1] % 10 == 0, f"{p} fuera de la grilla de ATPDraw"


@pytest.mark.parametrize("caso,opciones", CASOS_XML)
def test_nombres_de_nodo_validos_para_atp(caso, opciones):
    red = Red.cargar(caso)
    _, terminales, _ = _terminales_y_cables(generar_xml(red, **opciones))
    for _, n, _ in terminales:
        v = n.get("Value")
        assert v and n.get("UserNamed") == "true"
        # ATP: 6 caracteres; ATPDraw agrega A/B/C a los nodos trifásicos.
        assert len(v) <= (5 if n.get("NumPhases") == "3" else 6)
    assert {b.id.upper() for b in red.barras} <= {n.get("Value") for _, n, _ in terminales}


def test_parametros_iguales_al_modelo(ejemplo):
    raiz = ET.fromstring(generar_xml(ejemplo, "E2"))
    var = variables(ejemplo, "E2")
    r_lineas = sorted(_dato(cc, "R_1") for cc in _comp(raiz, "RLC3"))
    assert r_lineas == pytest.approx(sorted([float(var["LINEA_L_MT_R_OHM"]),
                                             float(var["LINEA_L_BT_R_OHM"])]), rel=1e-5)
    (t,) = _comp(raiz, "SATTRAFO")
    assert _dato(t, "CouplP") == 1000 and _dato(t, "CouplS") == 1000          # Yy0
    assert _dato(t, "Vrp") / _dato(t, "Vrs") == pytest.approx(13.2 / 0.22, rel=1e-5)
    assert _dato(t, "Rs") == pytest.approx(float(var["TRAFO_T1_R_BT_OHM"]), rel=1e-5)
    (f,) = _comp(raiz, "ACSOURCE")
    assert _dato(f, "AmplitudeA") == pytest.approx(13200)


def test_dyn5_y_cable_con_capacitancia(sub75):
    raiz = ET.fromstring(generar_xml(sub75))
    (t,) = _comp(raiz, "SATTRAFO")
    assert _dato(t, "CouplP") == 2000                                          # D en AT
    assert _dato(t, "CouplS") == 1000 + 150                                    # Y en BT a 150°
    assert _dato(t, "Vrp") == pytest.approx(11.4)                              # D: tensión de línea
    assert _dato(t, "Vrs") == pytest.approx(0.208 / math.sqrt(3), rel=1e-5)    # Y: tensión de fase
    (pi,) = _comp(raiz, "LINEPI3S")
    assert _dato(pi, "C+") == pytest.approx(200e-6)                            # 200 nF/km -> µF/m
    assert _dato(pi, "Length") == pytest.approx(100)


def test_tap_cambia_tension_de_devanado(ejemplo):
    def vrp(esc):
        (t,) = _comp(ET.fromstring(generar_xml(ejemplo, esc)), "SATTRAFO")
        return _dato(t, "Vrp")
    assert vrp("E3") == pytest.approx(vrp("E2") * (1 - 0.025), rel=1e-6)


def test_falla_agrega_red_y_quita_cargas(sub75):
    raiz = ET.fromstring(generar_xml(sub75, falla_3f="TGD"))
    (f,) = _comp(raiz, "ACSOURCE")
    assert _dato(f, "AmplitudeA") == pytest.approx(11400 * C_IEC)
    cargas = [cc for cc in _comp(raiz, "RLCY3") if _dato(cc, "R_1") > R_FALLA]
    assert cargas == []
    with pytest.raises(KeyError):
        generar_xml(sub75, falla_3f="NO_EXISTE")


def test_lis_reproduce_el_caso_de_4_barras(ejemplo):
    u = leer_lis(DATOS / "atp_4barras_E1_cargas_calibradas.lis", ejemplo)
    for b, valor in ejemplo.referencia["E1"]["u_pu"].items():
        assert u[b][0] == pytest.approx(valor, abs=2e-4), b


def test_lis_75kva_igual_a_pandapower_con_desfase(sub75):
    pp = obtener("pandapower").flujo(sub75, "base").barras
    u = leer_lis(DATOS / "atp_75kva_base_cargas_calibradas.lis", sub75)
    for b, r in pp.items():
        assert u[b][0] == pytest.approx(r.u_pu, abs=2e-4), b
        assert u[b][1] == pytest.approx(r.angulo_deg, abs=0.05), b   # Dyn5: BT ≈ -151°


@pytest.mark.parametrize("barra", ["PCC", "MT"])
def test_falla_en_mt_igual_a_iec60909(sub75, barra):
    ik_pp = obtener("pandapower").cortocircuito(sub75, "base").cortocircuito[barra].ikss_kA
    assert leer_falla(DATOS / f"atp_75kva_falla3f_{barra}.lis", sub75, barra) == pytest.approx(ik_pp, rel=1e-3)


def test_falla_en_bt_es_la_fisica_sin_factor_kt(sub75):
    """En BT ATP calcula la corriente física; IEC 60909 (pandapower) además corrige la
    impedancia del transformador con K_T = 0,95·c/(1+0,6·x_T) ≈ 1,025. Se compara con el
    cálculo a mano sin K_T, y se verifica que la diferencia con pandapower es ese factor."""
    c, un_mt, un_bt = C_IEC, 11.4, 0.208
    x, cab, t = sub75.redes_externas[0], sub75.lineas[0], sub75.transformadores[0]
    xq = c * un_bt ** 2 / x.scc_max_MVA / math.sqrt(1 + x.r_x_max ** 2)
    zq = complex(xq * x.r_x_max, xq)
    zcab = complex(cab.r_a(20) * cab.longitud_km, cab.x_ohm_km * cab.longitud_km) / (un_mt / un_bt) ** 2
    ukx = math.sqrt(t.uk_pct ** 2 - t.ukr_pct ** 2)
    zt = complex(t.ukr_pct, ukx) / 100 * un_bt ** 2 / t.sn_MVA
    ik_fisica = c * un_bt / (math.sqrt(3) * abs(zq + zcab + zt + R_FALLA))
    ik_atp = leer_falla(DATOS / "atp_75kva_falla3f_BT.lis", sub75, "BT")
    assert ik_atp == pytest.approx(ik_fisica, rel=5e-3)
    kt = 0.95 * c / (1 + 0.6 * ukx / 100)
    ik_iec = c * un_bt / (math.sqrt(3) * abs(zq + zcab + kt * zt))
    ik_pp = obtener("pandapower").cortocircuito(sub75, "base").cortocircuito["BT"].ikss_kA
    assert ik_pp == pytest.approx(ik_iec, rel=1e-3)


def test_exportar_escribe_xml(ejemplo, tmp_path):
    (ruta,) = obtener("atpdraw").exportar(ejemplo, tmp_path, "E1")
    assert ruta.name == "ejemplo_didactico_4_barras_E1.xml"
    assert ET.parse(ruta).getroot().get("Application") == "ATPDraw"
    (falla,) = obtener("atpdraw").exportar(ejemplo, tmp_path, "E1", falla_3f="B4")
    assert falla.name == "ejemplo_didactico_4_barras_E1_falla_B4.xml"
