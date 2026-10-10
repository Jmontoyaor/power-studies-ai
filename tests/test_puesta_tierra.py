"""Malla de puesta a tierra contra los ejemplos resueltos del Anexo B de IEEE Std 80-2013.

Datos comunes (B, p. 129): tf = 0,5 s, Sf = 0,6, ρ = 400 Ω·m, gravilla 2500 Ω·m de
0,102 m, h = 0,5 m, d = 0,01 m, 3I0 en 115 kV = 3180 A (IG) y 6814 A en 13 kV (calibre).
La norma redondea valores intermedios (Cs = 0,74; Rg = 2,78; Km = 0,89 y 0,77), por eso
la tolerancia es de 1 %, o la del redondeo publicado.
"""
import pytest

from power_studies.puesta_tierra import Falla, Malla, Suelo, calibre_minimo, disenar, tensiones_tolerables

SUELO = Suelo(rho=400, rho_s=2500, h_s=0.102)
FALLA = Falla(tres_i0=3180, sf=0.6, tf=0.5, i_calibre=6814)


def test_b1_malla_cuadrada_sin_varillas():
    r = disenar(SUELO, Malla(lx=70, ly=70, nx=11, ny=11, h=0.5, d=0.01), FALLA)
    assert r.cs == pytest.approx(0.74, abs=0.005)
    assert r.e_paso_tol == pytest.approx(2686.6, rel=0.01)
    assert r.e_toque_tol == pytest.approx(838.2, rel=0.01)
    assert r.rg == pytest.approx(2.78, abs=0.005)
    assert r.ig == pytest.approx(1908, rel=1e-3)
    assert r.gpr == pytest.approx(5304, rel=0.01)
    assert r.n == pytest.approx(11)
    assert r.kii == pytest.approx(0.57, abs=0.005)
    assert r.km == pytest.approx(0.89, abs=0.005)
    assert r.ki == pytest.approx(2.272, abs=1e-3)
    assert r.em == pytest.approx(1002.1, rel=0.01)
    assert not r.cumple_toque          # la norma concluye que hay que modificar el diseño


def test_b1_calibre_del_conductor():
    # 6,814 kA · 7,06 · √0,5 = 34,02 kcmil = 17,2 mm² (cobre duro)
    assert calibre_minimo(6814, 0.5, "cu_duro") == pytest.approx(17.2, abs=0.05)
    r = disenar(SUELO, Malla(lx=70, ly=70, nx=11, ny=11, h=0.5, d=0.01), FALLA)
    assert r.seccion_min_mm2 == pytest.approx(17.2, abs=0.05)


def test_b2_malla_cuadrada_con_20_varillas():
    m = Malla(lx=70, ly=70, nx=11, ny=11, h=0.5, d=0.01, n_varillas=20, l_varilla=7.5)
    r = disenar(SUELO, m, FALLA)
    assert r.rg == pytest.approx(2.75, abs=0.005)
    assert r.kii == 1.0
    assert r.km == pytest.approx(0.77, abs=0.005)
    assert r.em == pytest.approx(747.4, rel=0.01)
    assert r.ks == pytest.approx(0.406, abs=0.001)
    assert r.es == pytest.approx(548.9, rel=0.01)
    assert r.cumple                    # 747,4 < 838,2 y 548,9 < 2686,6


def test_b3_malla_rectangular_con_38_varillas():
    # 63 m x 84 m, patrón 10 x 13: LC = 13·63 + 10·84 = 1659 m
    m = Malla(lx=84, ly=63, nx=10, ny=13, h=0.5, d=0.01, n_varillas=38, l_varilla=10)
    assert m.lc == 1659 and m.espaciamiento == pytest.approx(7)
    r = disenar(SUELO, m, FALLA)
    assert r.rg == pytest.approx(2.62, abs=0.005)
    assert r.n == pytest.approx(11.35, abs=0.01)
    assert r.ki == pytest.approx(2.324, abs=0.002)
    assert r.em == pytest.approx(595.8, rel=0.01)


def test_tolerables_50_kg_mas_exigentes_que_70():
    paso50, toque50 = tensiones_tolerables(SUELO, 0.5, 50)
    paso70, toque70 = tensiones_tolerables(SUELO, 0.5, 70)
    assert paso50 / paso70 == pytest.approx(0.116 / 0.157)
    assert toque50 < toque70


def test_sin_capa_superficial_cs_es_1():
    from power_studies.puesta_tierra import factor_cs
    assert factor_cs(Suelo(rho=100)) == 1.0


def test_plantilla_yaml_reproduce_b2():
    """casos/ieee80_ejemplo_b2/malla.yaml es la plantilla para diseños nuevos."""
    from pathlib import Path

    import yaml

    raiz = Path(__file__).resolve().parents[1]
    d = yaml.safe_load((raiz / "casos" / "ieee80_ejemplo_b2" / "malla.yaml").read_text(encoding="utf-8"))
    r = disenar(Suelo(**d["suelo"]), Malla(**d["malla"]), Falla(**d["falla"]), d["peso_kg"], d["material"])
    assert r.em == pytest.approx(747.4, rel=0.01) and r.es == pytest.approx(548.9, rel=0.01)
    assert r.cumple
