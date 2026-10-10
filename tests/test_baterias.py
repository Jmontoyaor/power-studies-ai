"""Banco de baterías contra el ejemplo de la Figura A.1 de IEEE Std 485-2020 (Anexo A).

Ciclo de la Tabla A.1, celda hipotética XYZ (ABC Co.), 1,75 V/celda, 18,3 °C (65 °F).
Factores Kt leídos de la columna (6B) de la planilla.
"""
import pytest

from power_studies.baterias import (Periodo, celda_comercial, dimensionar, factor_temperatura,
                                    numero_celdas, tension_minima_celda)

CICLO = [Periodo(320, 1), Periodo(100, 29), Periodo(280, 30), Periodo(200, 60), Periodo(40, 59), Periodo(120, 1)]
KT = {1: 0.77, 30: 1.44, 59: 2.00, 60: 2.00, 90: 2.46, 119: 2.91, 120: 2.91, 150: 3.33, 179: 3.72, 180: 3.72}
# Errata de la Figura A.1: en la sección 3 el periodo 3 dice "T = M3 = 1", pero M3 = 30 min y el
# factor usado (1,44 -> 180 A · 1,44 = 259,2) es el de 30 min.


def test_a2_numero_de_celdas_y_tension_minima():
    assert numero_celdas(140, 2.33)[0] == 60 and tension_minima_celda(105, 60) == pytest.approx(1.75)
    n, v_igualacion = numero_celdas(135, 2.33)      # 57,94 -> 58 celdas (A.2.2)
    assert n == 58 and v_igualacion > 135           # redondeó hacia arriba: hay que verificar la carga
    assert tension_minima_celda(105, 58) == pytest.approx(1.81, abs=0.005)


def test_figura_a1_secciones():
    r = dimensionar(CICLO, KT, "kt", Periodo(100, 1), 18.3, 1.15, 1.25)
    assert set(r.secciones) == {1, 3, 4, 6}         # 2 y 5 se omiten: A3 > A2 y A6 > A5
    assert r.secciones[1] == pytest.approx(246.4)
    assert r.secciones[3] == pytest.approx(459.2)
    assert r.secciones[4] == pytest.approx(573.8)
    assert r.secciones[6] == pytest.approx(480.2)
    assert r.seccion_maxima == 4


def test_figura_a1_tamano_corregido():
    r = dimensionar(CICLO, KT, "kt", Periodo(100, 1), 18.3, 1.15, 1.25)
    assert r.tamano_aleatorio == pytest.approx(77.0)
    assert r.sin_corregir == pytest.approx(650.8)
    assert r.factor_temperatura == 1.08
    assert r.corregido == pytest.approx(1010.4, abs=0.1)
    assert celda_comercial(r.corregido, [800, 920, 1040, 1160]) == 1040   # XYZ-27


def test_factor_temperatura_tabla_1():
    assert factor_temperatura(25.0) == 1.000
    assert factor_temperatura(10.0) == 1.190
    assert factor_temperatura(11.4) == pytest.approx(1.17)   # interpolado y redondeado a 2 decimales
    assert factor_temperatura(35.0) == 1.0                    # sobre 25 °C no se reduce el tamaño
    with pytest.raises(ValueError):
        factor_temperatura(0.0)


def test_rt_da_placas_positivas():
    rt = {t: 100 / k for t, k in KT.items()}      # Rt proporcional a 1/Kt (6.4.3)
    r = dimensionar(CICLO, rt, "rt", temperatura_c=25, margen=1.0, envejecimiento=1.0)
    assert r.unidad == "placas positivas"
    assert r.tamano_ciclo == pytest.approx(573.8 / 100)


def test_tiempo_fuera_de_la_tabla_del_fabricante():
    with pytest.raises(ValueError, match="fuera de la tabla"):
        dimensionar(CICLO, {1: 0.77, 60: 2.0}, "kt")


def test_avisa_cuando_interpola_el_factor():
    sin_30 = {k: v for k, v in KT.items() if k != 30}
    r = dimensionar(CICLO, sin_30, "kt", Periodo(100, 1), 18.3, 1.15, 1.25)
    assert any("t = 30" in n for n in r.notas)
    assert not dimensionar(CICLO, KT, "kt", Periodo(100, 1), 18.3, 1.15, 1.25).notas


def test_plantilla_yaml_reproduce_figura_a1():
    """casos/ieee485_ejemplo_a1/baterias.yaml es la plantilla para bancos nuevos."""
    from pathlib import Path

    import yaml

    d = yaml.safe_load((Path(__file__).resolve().parents[1] / "casos" / "ieee485_ejemplo_a1"
                        / "baterias.yaml").read_text(encoding="utf-8"))
    c = d["celda"]
    r = dimensionar([Periodo(**p) for p in d["ciclo"]], {float(k): v for k, v in c["factores"].items()},
                    c["tipo_factor"], Periodo(**d["aleatoria"]), d["temperatura_c"], d["margen"],
                    d["envejecimiento"])
    assert r.corregido == pytest.approx(1010.4, abs=0.1)
    assert celda_comercial(r.corregido, c["comerciales"]) == 1040



# IEEE 946-2020, Anexo B. La norma redondea K = 1,07 · 1,10 = 1,177 a 1,18: tolerancia 0,5 %.
def test_946_b3_generacion():
    from power_studies.baterias import cargador
    r = cargador(400, 12, 100, "VLA", [1.07, 1.10], i_no_continua=80)
    assert r.ic == pytest.approx(161.3, rel=5e-3)
    assert r.i2 == pytest.approx(212.4, rel=5e-3)
    assert r.i3 == r.i2


def test_946_b4_subestacion():
    from power_studies.baterias import cargador
    r = cargador(150, 12, 25, "VLA", comerciales=[20, 30, 40, 50])
    assert r.ic == pytest.approx(38.8, abs=0.05)
    assert r.comercial == 40


def test_ah_extraidos_del_ciclo():
    from power_studies.baterias import ah_extraidos
    # 320·1 + 100·29 + 280·30 + 200·60 + 40·59 + 120·1 + 100·1 (aleatoria) = 26 200 A·min
    assert ah_extraidos(CICLO, Periodo(100, 1)) == pytest.approx(26200 / 60)
