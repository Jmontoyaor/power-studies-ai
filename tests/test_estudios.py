import json
import math
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("NUMBA_DISABLE_JIT", "1")

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "herramientas" / "powerfactory"))
sys.path.insert(0, str(Path(__file__).parent))

from power_studies.adaptadores import REGISTRO, obtener  # noqa: E402
from power_studies.adaptadores.plantillas_ad import rellenar, variables  # noqa: E402
from power_studies.diagrama import auto_layout, dibujar  # noqa: E402
from power_studies.informe import generar  # noqa: E402
from power_studies.modelo import Red  # noqa: E402
from power_studies.normas import verificar  # noqa: E402
from power_studies.resultados import comparar  # noqa: E402
from power_studies.validacion import contra_referencia  # noqa: E402

EJEMPLO = RAIZ / "casos" / "ejemplo_4_barras" / "red.yaml"
SUB75 = RAIZ / "casos" / "subestacion_75kva" / "red.yaml"


@pytest.fixture
def ejemplo():
    return Red.cargar(EJEMPLO)


@pytest.fixture
def sub75():
    return Red.cargar(SUB75)


# ---------------------------------------------------------------- modelo
def test_modelo_rechaza_barra_inexistente(ejemplo):
    d = ejemplo.model_dump()
    d["lineas"][0]["hasta"] = "NO_EXISTE"
    with pytest.raises(ValueError, match="no existe"):
        Red.model_validate(d)


def test_modelo_rechaza_tension_trafo_incoherente(ejemplo):
    d = ejemplo.model_dump()
    d["transformadores"][0]["un_bt_kV"] = 0.48
    with pytest.raises(ValueError, match="no coincide"):
        Red.model_validate(d)


def test_correccion_temperatura(ejemplo):
    cable = ejemplo.lineas[1]
    assert cable.r_a(75) == pytest.approx(0.33)
    assert cable.r_a(20) == pytest.approx(0.33 * 254.5 / 309.5)


def test_ida_y_vuelta_yaml(tmp_path, sub75):
    sub75.guardar(tmp_path / "r.yaml")
    assert Red.cargar(tmp_path / "r.yaml") == sub75


# ---------------------------------------------------- validación numérica
@pytest.mark.parametrize("esc", ["E1", "E2"])
def test_pandapower_reproduce_newton_raphson_del_informe(ejemplo, esc):
    res = obtener("pandapower").flujo(ejemplo, esc)
    ok, det = contra_referencia(ejemplo, res, tol_u_pu=0.0002)
    assert res.convergio and ok, det


def test_tap_e3_dentro_de_tolerancia(ejemplo):
    res = obtener("pandapower").flujo(ejemplo, "E3")
    ok, det = contra_referencia(ejemplo, res, tol_u_pu=0.001)
    assert ok, det


def test_flujos_e2(ejemplo):
    r = obtener("pandapower").flujo(ejemplo, "E2").ramas
    assert r["L_BT"].p_MW * 1000 == pytest.approx(46.53, abs=0.05)
    assert r["L_BT"].q_Mvar * 1000 == pytest.approx(22.45, abs=0.05)
    assert r["L_BT"].i_kA * 1000 == pytest.approx(139.2, abs=0.2)
    assert r["T1"].cargabilidad_pct == pytest.approx(93.5, abs=0.2)


def test_subestacion_reproduce_unifilar_powerfactory(sub75):
    res = obtener("pandapower").flujo(sub75, "base")
    ok, det = contra_referencia(sub75, res, tol_u_pu=0.006, tol_carga_pct=1.0)
    assert ok, det
    assert res.barras["TGD"].angulo_deg == pytest.approx(-151.2, abs=0.3)  # Dyn5


@pytest.mark.parametrize("caso", [EJEMPLO, SUB75])
def test_validacion_cruzada_pandapower_opendss(caso):
    pytest.importorskip("opendssdirect")
    red = Red.cargar(caso)
    for e in red.escenarios:
        a = obtener("pandapower").flujo(red, e.id)
        b = obtener("opendss").flujo(red, e.id)
        assert comparar(a, b, tol_u_pu=0.001, tol_carga_pct=0.5) == []


def test_cortocircuito_en_pcc_igual_a_scc(sub75):
    res = obtener("pandapower").cortocircuito(sub75)
    # Scc de la red externa es la potencia de falla en su barra: Ik'' = Scc/(sqrt3*Un)
    assert res.cortocircuito["PCC"].ikss_kA == pytest.approx(150 / (math.sqrt(3) * 11.4), rel=0.01)
    # aguas abajo la corriente en kA crece en BT y la potencia de falla cae
    assert res.cortocircuito["TGD"].skss_MVA < res.cortocircuito["BT"].skss_MVA < 150


# ------------------------------------------------------------- normas
def test_normas_reproducen_conclusion_del_informe(ejemplo):
    """Informe Sec. 6: a 20 °C la caída del alimentador cumple (2,67 %);
    a 75 °C no cumple (3,14 %)."""
    def caida(esc):
        v = verificar(ejemplo, obtener("pandapower").flujo(ejemplo, esc))
        return next(x for x in v if x.criterio == "Caída en alimentador BT")
    e1, e2 = caida("E1"), caida("E2")
    assert e1.valor == pytest.approx(2.67, abs=0.01) and e1.estado == "cumple"
    assert e2.valor == pytest.approx(3.14, abs=0.01) and e2.estado == "no cumple"


# ------------------------------------------------- gráfico e informe
def test_layout_radial(sub75):
    auto_layout(sub75, sobrescribir=True)
    ys = [b.pos.y for b in sub75.barras]
    assert ys == sorted(ys, reverse=True)  # de arriba hacia abajo


def test_unifilar_e_informe(tmp_path, sub75):
    res = obtener("pandapower").flujo(sub75, "base")
    figs = dibujar(sub75, res, tmp_path / "u")
    assert all(f.stat().st_size > 1000 for f in figs)
    doc = generar(sub75, {"base": res}, tmp_path / "inf.docx",
                  textos={"conclusiones": "Confirmar calibre del alimentador."})
    assert doc.stat().st_size > 20000


# ------------------------------------------------------- plantillas
def test_plantilla_atp_columnas_fijas(ejemplo, tmp_path):
    plantilla = RAIZ / "plantillas" / "atp" / "falla_3f_ejemplo.atp"
    rutas = obtener("atp").exportar(ejemplo, tmp_path, "E2", plantilla=plantilla)
    texto = rutas[-1].read_text(encoding="latin-1")
    assert "{{" not in texto
    for linea in texto.splitlines():
        if linea.startswith("  N1A   N2A"):
            r = float(linea[26:32])
            assert r == pytest.approx(0.54 * 309.5 / 254.5, rel=1e-3)  # R a 75 °C


def test_plantilla_variable_faltante():
    out, faltan = rellenar("x={{NO_EXISTE}}", {})
    assert faltan == ["NO_EXISTE"]


def test_variables_cubren_todos_los_elementos(sub75):
    v = variables(sub75)
    assert "TRAFO_TR1_RELACION" in v and "LINEA_ALIM_BT_R_OHM" in v and "CARGA_CARGA_KW" in v


def test_exportaciones(tmp_path, sub75):
    for h in ("powerfactory", "etap", "pvsyst", "opendss", "pandapower"):
        rutas = obtener(h).exportar(sub75, tmp_path / h)
        assert rutas and all(Path(r).exists() for r in rutas)
    assert set(REGISTRO) >= {"pandapower", "opendss", "powerfactory", "atp", "etap", "pvsyst"}


# ------------------------------------------------- PowerFactory (simulado)
def test_powerfactory_construir_y_reexportar(tmp_path, sub75):
    """Construye la red con pf_construir_red.py sobre una API simulada,
    la vuelve a exportar con pf_exportar_modelo.py y comprueba que el modelo
    neutro sobrevive el viaje de ida y vuelta."""
    import fake_powerfactory as fpf
    import pf_construir_red as pfc
    import pf_exportar_modelo as pfe

    from power_studies.adaptadores.powerfactory_ad import desde_exportacion

    auto_layout(sub75)
    m = tmp_path / "modelo.json"
    sub75.guardar(m)
    app = fpf.App()
    res = pfc.main(app, str(m), str(tmp_path / "res.json"))
    assert res["convergio"]
    red_pf = app.carpetas["netdat"].GetContents("*.ElmNet")[0]
    assert len(red_pf.GetContents("*.ElmTerm")) == 4
    tr = red_pf.GetContents("TR1.ElmTr2")[0]
    assert (tr.typ_id.tr2cn_h, tr.typ_id.tr2cn_l, tr.typ_id.nt2ag) == ("D", "YN", 5)
    assert tr.bushv.cterm.loc_name == "MT" and tr.buslv.cterm.loc_name == "BT"
    # el unifilar se dibujó (estrategia manual, porque la API simulada no tiene auto-layout)
    dia = app.carpetas["dia"].GetContents("*.IntGrfnet")[0]
    assert len(dia.GetContents("*.IntGrf")) == 4 + 1 + 2 + 1 + 1

    exp = tmp_path / "exportado.json"
    pfe.exportar(app, str(exp))
    vuelta = desde_exportacion(exp)
    assert {b.id for b in vuelta.barras} == {b.id for b in sub75.barras}
    t2 = vuelta.transformadores[0]
    assert (t2.sn_MVA, t2.uk_pct, t2.grupo.upper()) == (0.075, 3.5, "DYN5")
    alim = next(l for l in vuelta.lineas if l.id == "ALIM_BT")
    # la exportación trae R ya corregida a la temperatura del escenario (20 °C)
    assert alim.r_ohm_km == pytest.approx(sub75.lineas[1].r_a(20))
    assert vuelta.barras[0].pos is not None


def test_powerfactory_usa_autolayout_si_existe(tmp_path, ejemplo):
    import fake_powerfactory as fpf
    import pf_construir_red as pfc

    m = tmp_path / "m.json"
    ejemplo.guardar(m)
    c = pfc.Constructor(fpf.App(con_layout=True), json.loads(m.read_text()))
    c.construir()
    assert c.dibujar() == "automatico"
