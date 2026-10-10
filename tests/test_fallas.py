"""Fallas asimétricas (paso 2 de docs/hoja_de_ruta.md).

Referencia independiente: componentes simétricas a mano. ATP debe dar la
corriente física (sin K_T) y pandapower la de IEC 60909, que además multiplica
las impedancias de los transformadores de red por K_T = 0,95·c/(1+0,6·x_T).
Los `datos/atp_75kva_falla*.lis` son salida real de ATP para estos casos.
"""
import cmath
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from power_studies.adaptadores import obtener
from power_studies.adaptadores.atpdraw_ad import C_IEC, R_ABIERTO, R_FALLA, generar_xml, leer_falla
from power_studies.modelo import Red

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "casos" / "ejemplo_4_barras" / "red.yaml"
SUB75 = RAIZ / "casos" / "subestacion_75kva" / "red.yaml"
DATOS = Path(__file__).parent / "datos"
A = cmath.exp(2j * math.pi / 3)


@pytest.fixture(scope="module")
def sub75():
    return Red.cargar(SUB75)


def _secuencias(red: Red, kt: bool) -> dict[str, tuple[complex, complex, float]]:
    """(Z1, Z0, Un en kV) vistos desde cada barra del caso de 75 kVA (escenario base, 20 °C)."""
    x, cab, t, alim = red.redes_externas[0], red.lineas[0], red.transformadores[0], red.lineas[1]
    un_mt, un_bt = t.un_at_kV, t.un_bt_kV
    xq = C_IEC * un_mt ** 2 / x.scc_max_MVA / math.sqrt(1 + x.r_x_max ** 2)
    zq1, xq0 = complex(xq * x.r_x_max, xq), xq * x.x0_x1
    zq0 = complex(xq0 * x.r0_x0, xq0)
    zc1 = complex(cab.r_a(20) * cab.longitud_km, cab.x_ohm_km * cab.longitud_km)
    zc0 = complex(cab.r0_ohm_km * cab.longitud_km, cab.x0_ohm_km * cab.longitud_km)
    ukx = math.sqrt(t.uk_pct ** 2 - t.ukr_pct ** 2)
    zt = complex(t.ukr_pct, ukx) / 100 * un_bt ** 2 / t.sn_MVA
    if kt:
        zt *= 0.95 * C_IEC / (1 + 0.6 * ukx / 100)
    za1 = complex(alim.r_a(20) * alim.longitud_km, alim.x_ohm_km * alim.longitud_km)
    za0 = complex(alim.r0_ohm_km * alim.longitud_km, alim.x0_ohm_km * alim.longitud_km)
    k = (un_bt / un_mt) ** 2
    # Dyn5: el delta de MT bloquea la secuencia cero; en BT solo la aporta el transformador.
    return {"PCC": (zq1, zq0, un_mt), "MT": (zq1 + zc1, zq0 + zc0, un_mt),
            "BT": ((zq1 + zc1) * k + zt, zt, un_bt), "TGD": ((zq1 + zc1) * k + zt + za1, zt + za0, un_bt)}


def _ik(tipo: str, z1: complex, z0: complex, un: float, rf: float = 0.0) -> float:
    """Corriente de falla (kA) con componentes simétricas; Z2 = Z1; rf por fase."""
    e = C_IEC * un * 1000 / math.sqrt(3)
    if tipo == "1f":
        return abs(3 * e / (2 * z1 + z0 + 3 * rf)) / 1000
    if tipo == "2f":
        return abs(math.sqrt(3) * e / (2 * z1 + 2 * rf)) / 1000
    a1, a2, a0 = z1 + rf, z1 + rf, z0 + rf          # 2FT: fases B y C a tierra
    i1 = e / (a1 + a2 * a0 / (a2 + a0))
    i2, i0 = -i1 * a0 / (a2 + a0), -i1 * a2 / (a2 + a0)
    return max(abs(i0 + A * A * i1 + A * i2), abs(i0 + A * i1 + A * A * i2)) / 1000


@pytest.mark.parametrize("tipo,barra", [("1f", "MT"), ("1f", "BT"), ("2f", "BT"), ("2ft", "MT"), ("2ft", "BT")])
def test_atp_es_la_fisica_de_componentes_simetricas(sub75, tipo, barra):
    z1, z0, un = _secuencias(sub75, kt=False)[barra]
    atp = leer_falla(DATOS / f"atp_75kva_falla{tipo}_{barra}.lis", sub75, barra)
    assert atp == pytest.approx(_ik(tipo, z1, z0, un, R_FALLA), rel=1e-3)


@pytest.mark.parametrize("tipo", ["1f", "2f"])
def test_pandapower_es_iec60909_con_kt(sub75, tipo):
    res = obtener("pandapower").cortocircuito(sub75, "base", tipo).fallas[tipo]
    for barra, (z1, z0, un) in _secuencias(sub75, kt=True).items():
        assert res[barra].ikss_kA == pytest.approx(_ik(tipo, z1, z0, un), rel=1e-3), barra


def test_bifasica_es_raiz3_medios_de_la_trifasica(sub75):
    pp = obtener("pandapower")
    i3 = pp.cortocircuito(sub75, "base").cortocircuito
    i2 = pp.cortocircuito(sub75, "base", "2f").fallas["2f"]
    for b in i3:
        assert i2[b].ikss_kA == pytest.approx(i3[b].ikss_kA * math.sqrt(3) / 2, rel=1e-4)


def test_falla_a_tierra_sin_secuencia_cero_avisa_que_falta():
    red = Red.cargar(EJEMPLO)  # no trae datos de secuencia cero
    assert red.faltantes_secuencia_cero()
    with pytest.raises(ValueError, match="secuencia cero"):
        obtener("pandapower").cortocircuito(red, "E1", "1f")
    with pytest.raises(ValueError, match="secuencia cero"):
        generar_xml(red, "E1", falla="B4", tipo_falla="1f")
    generar_xml(red, "E1", falla="B4", tipo_falla="2f")  # la bifásica no la necesita


def test_pandapower_no_inventa_la_2ft(sub75):
    with pytest.raises(NotImplementedError):
        obtener("pandapower").cortocircuito(sub75, "base", "2ft")


@pytest.mark.parametrize("tipo,fases,neutro_a_tierra", [
    ("1f", (R_FALLA, R_ABIERTO, R_ABIERTO), True),
    ("2f", (R_ABIERTO, R_FALLA, R_FALLA), False),
    ("2ft", (R_ABIERTO, R_FALLA, R_FALLA), True),
    ("3f", (R_FALLA, R_FALLA, R_FALLA), True),
])
def test_elemento_de_falla_por_tipo(sub75, tipo, fases, neutro_a_tierra):
    raiz = ET.fromstring(generar_xml(sub75, falla="BT", tipo_falla=tipo))
    (f,) = [c.find("comp_content") for c in raiz.iter("comp") if c.get("Name") == "RLCY3"]
    rs = tuple(float(f.find(f"data[@Name='R_{k}']").get("Value")) for k in (1, 2, 3))
    assert rs == pytest.approx(fases)
    out = f.find("node[@Name='OUT']")
    assert (out.get("Ground") == "1") is neutro_a_tierra
    if not neutro_a_tierra:
        assert out.get("Value") == "FALLN"
