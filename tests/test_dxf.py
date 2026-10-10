"""Exportación a AutoCAD (DXF): el archivo es válido y contiene lo que el modelo dice."""
import pytest

ezdxf = pytest.importorskip("ezdxf")

from power_studies.dxf import planta_malla, posiciones_varillas, unifilar_subestacion  # noqa: E402
from power_studies.puesta_tierra import Falla, Malla, Suelo, disenar  # noqa: E402
from power_studies.subestacion import Bahia, Subestacion, armar  # noqa: E402

MALLA_B2 = Malla(70, 70, 11, 11, 0.5, 0.01, 20, 7.5)


def _capa(doc, capa, tipo):
    return [e for e in doc.modelspace() if e.dxf.layer == capa and e.dxftype() == tipo]


def test_planta_de_malla(tmp_path):
    r = disenar(Suelo(400, 2500, 0.102), MALLA_B2, Falla(3180, 0.6, 0.5))
    doc = ezdxf.readfile(planta_malla(MALLA_B2, tmp_path / "m.dxf", r))
    assert not doc.audit().has_errors
    assert doc.header["$INSUNITS"] == 6                      # metros
    lineas = _capa(doc, "MALLA", "LINE")
    assert len(lineas) == 11 + 11
    assert sum(e.dxf.start.distance(e.dxf.end) for e in lineas) == pytest.approx(MALLA_B2.lc)
    assert len(_capa(doc, "VARILLAS", "CIRCLE")) == 20
    textos = " ".join(e.dxf.text for e in doc.modelspace().query("TEXT"))
    assert "CUMPLE" in textos and "Rg = 2.753" in textos


def test_varillas_en_esquinas_y_perimetro():
    pts = posiciones_varillas(MALLA_B2)
    assert len(pts) == 20
    assert {(0.0, 0.0), (70.0, 0.0), (70.0, 70.0), (0.0, 70.0)} <= {(round(x, 6), round(y, 6)) for x, y in pts}
    assert all(x in (0, 70) or y in (0, 70) for x, y in ((round(a, 6), round(b, 6)) for a, b in pts))


@pytest.mark.parametrize("conf", ["SBSB", "MTB", "DBSB", "BAH", "DBDB", "RB"])
def test_unifilar_dxf(tmp_path, conf):
    t = armar(Subestacion("prueba", 115, conf, [Bahia("L1"), Bahia("L2"), Bahia("T1", "transformador"),
                                                 Bahia("T2", "transformador")]))
    doc = ezdxf.readfile(unifilar_subestacion(t, tmp_path / "u.dxf"))
    assert not doc.audit().has_errors
    assert {"BARRAS", "EQUIPOS", "CONDUCTORES", "SALIDAS", "TEXTOS"} <= {l.dxf.name for l in doc.layers}
    cuadros = [e for e in _capa(doc, "EQUIPOS", "LWPOLYLINE") if e.closed and len(e) == 4]
    assert len(cuadros) == len(t.interruptores())
    textos = {e.dxf.text for e in doc.modelspace().query("TEXT")}
    assert {"L1", "L2", "T1", "T2"} <= textos
