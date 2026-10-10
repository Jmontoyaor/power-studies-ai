"""Configuraciones de barras: conteo de equipos y confiabilidad contra propiedades de libro.

- Interruptores para n circuitos: SBSB n, MTB n+1, DBSB n+1, BAH 1,5n, DBDB 2n, RB n.
- Falla en barra: SBSB y MTB (barra principal) pierden todo; DBSB pierde los circuitos
  de esa barra; BAH, DBDB y RB no pierden circuitos.
- Mantenimiento de un interruptor: SBSB y DBSB sacan el circuito; MTB (por la barra de
  transferencia), BAH, DBDB y RB lo mantienen en servicio.
"""
import pytest

from power_studies.subestacion import (Bahia, Subestacion, armar, dibujar, interruptores_esperados,
                                       resumen_confiabilidad)

CONFS = ("SBSB", "MTB", "DBSB", "BAH", "DBDB", "RB")


def _sub(conf, n=6):
    return armar(Subestacion("prueba", 115, conf, [Bahia(f"C{i + 1}") for i in range(n)]))


@pytest.mark.parametrize("conf", CONFS)
@pytest.mark.parametrize("n", [4, 6])
def test_numero_de_interruptores(conf, n):
    assert len(_sub(conf, n).interruptores()) == interruptores_esperados(conf, n)


@pytest.mark.parametrize("conf,perdidos", [("SBSB", 6), ("MTB", 6), ("DBSB", 3), ("BAH", 0), ("DBDB", 0), ("RB", 0)])
def test_peor_falla_en_barra(conf, perdidos):
    assert resumen_confiabilidad(_sub(conf))["max_perdidos_falla_barra"] == perdidos


@pytest.mark.parametrize("conf,perdidos", [("SBSB", 1), ("MTB", 0), ("DBSB", 1), ("BAH", 0), ("DBDB", 0), ("RB", 0)])
def test_mantenimiento_de_un_interruptor(conf, perdidos):
    assert resumen_confiabilidad(_sub(conf))["max_perdidos_mantenimiento_52"] == perdidos


def test_falla_en_barra_de_transferencia_no_afecta():
    t = _sub("MTB")
    assert t.perdidos_por_falla_en_barra("BT") == set()      # normalmente desenergizada
    assert t.perdidos_por_falla_en_barra("BP") == set(t.circuitos)


def test_dbsb_pierde_solo_los_circuitos_de_la_barra_fallada():
    t = _sub("DBSB")
    assert t.perdidos_por_falla_en_barra("B1") == {"C1", "C3", "C5"}
    assert t.perdidos_por_falla_en_barra("B2") == {"C2", "C4", "C6"}


def test_cada_circuito_tiene_seccionador_de_salida_con_puesta_a_tierra():
    for conf in CONFS:
        t = _sub(conf)
        for c in t.circuitos:
            assert any(e.puesta_tierra and c in (e.n1, e.n2) for e in t.seccionadores()), (conf, c)


def test_validaciones():
    with pytest.raises(ValueError, match="número par"):
        _sub("BAH", 5)
    with pytest.raises(ValueError, match="no soportada"):
        _sub("XYZ")


def test_dibuja_png_y_svg(tmp_path):
    rutas = dibujar(_sub("BAH", 4), f"{tmp_path / 'u.png'},{tmp_path / 'u.svg'}")
    assert all(r.exists() and r.stat().st_size > 1000 for r in rutas)
