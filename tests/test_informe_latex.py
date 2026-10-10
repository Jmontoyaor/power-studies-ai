"""Informe LaTeX: el planificador decide las secciones según los insumos y el .tex compila."""
from pathlib import Path

import pytest

from power_studies.informe_latex import compilador, esc, generar, nm, num, planificar

CASOS = Path(__file__).resolve().parents[1] / "casos"
EJEMPLO = CASOS / "informe_ejemplo" / "estudio.yaml"


def _plan(**m):
    return planificar(m, CASOS / "informe_ejemplo")


def test_solo_malla():
    p = _plan(malla="malla.yaml")
    assert "malla" in p.secciones and "flujo" not in p.secciones and "baterias" not in p.secciones
    assert p.anexos == ["datos", "normas"]


def test_malla_enlazada_a_la_red_trae_el_cortocircuito():
    p = _plan(red="../subestacion_75kva/red.yaml", malla="malla.yaml")   # sin pedir cortocircuito
    assert "cortocircuito" in p.secciones
    assert any("falla 1F" in r for r in p.razones)


def test_red_sin_cortocircuito():
    p = _plan(red="../subestacion_75kva/red.yaml")
    assert p.secciones == ["sistema", "flujo"]


def test_baterias_con_cargador_lo_menciona():
    p = _plan(baterias="../ieee485_ejemplo_a1/baterias.yaml")
    assert any("IEEE 946" in r for r in p.razones)


def test_manifiesto_vacio():
    with pytest.raises(ValueError, match="ningún insumo"):
        _plan(titulo="nada")


def test_escapes_y_numeros():
    assert esc("50% & $x_1") == r"50\% \& \$x\_1"
    assert esc("Ω") == r"$\Omega$"
    assert num(1234.5, 1) == "1.234,5" and nm(0.7429, 4) == "0{,}7429"


def test_tex_con_todas_las_memorias(tmp_path):
    rutas = generar(EJEMPLO, tmp_path, compilar=False)
    tex = rutas["tex"].read_text(encoding="utf-8")
    for titulo in ("Alcance", "Descripción del sistema", "Flujo de cargas", "Corrientes de cortocircuito",
                   "malla de puesta a tierra", "banco de baterías", "Cargador (IEEE Std 946-2020)",
                   "Configuración de la subestación", "Datos de entrada", "Normas, ecuaciones y observaciones"):
        assert titulo in tex, titulo
    assert r"\tag{57}" in tex and r"\tag{33}" in tex             # ecuaciones con número de IEEE 80
    assert "Recomendación de rediseño" in tex                      # 7280 A no cumple con la malla B.2
    assert (tmp_path / "planta_malla.png").exists() and (tmp_path / "unifilar_subestacion.png").exists()


@pytest.mark.skipif(compilador() is None, reason="no hay compilador de LaTeX")
def test_compila_pdf(tmp_path):
    rutas = generar(EJEMPLO, tmp_path)
    assert rutas["pdf"].stat().st_size > 50_000
