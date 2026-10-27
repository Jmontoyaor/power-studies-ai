"""Retroalimentación: cada programa aprende de sus archivos reales, de forma incremental."""
import pytest

from power_studies import retroalimentacion as r

DSS = """! red de prueba
New Circuit.prueba basekv=13.2
New LineCode.336ACSR nphases=3 r1=0.306 x1=0.627 units=mi
New Line.L1 bus1=a bus2=b linecode=336ACSR
~ length=1.2 units=km
New Transformer.T1 phases=3 windings=2 buses=(b, c) conns=(delta, wye) kvs=(13.2, 0.22) kvas=(75, 75)
New Load.C1 bus1=c kw=45 kvar=21.8
"""
DGS = """1;ID(a:40);Descr(a:40);Version(a:5)
$$ElmTerm;ID(a:40);loc_name(a:40);uknom(r)
1;B1;13.2
$$ElmLne;ID(a:40);loc_name(a:40);dline(r);bus1(p);bus2(p)
"""
PAN = """PVObject_=pvModule
  Comment=Módulo de prueba
  PNom=550.0
  Isc=13.9
  Voc=49.8
End of PVObject pvModule
"""


def _correr(tmp_path, programa, archivos):
    carpeta = tmp_path / programa
    carpeta.mkdir(exist_ok=True)
    for nombre, contenido in archivos.items():
        (carpeta / nombre).write_text(contenido, encoding="utf-8") if isinstance(contenido, str) else contenido(carpeta / nombre)
    return r.retroalimentar([programa], tmp_path / "k", {programa: [carpeta]}, silencio=True)


def test_opendss_clases_y_propiedades(tmp_path):
    aprendido = _correr(tmp_path, "opendss", {"red.dss": DSS})["opendss"]
    assert {"Circuit", "Linecode", "Line", "Transformer", "Load"} <= set(aprendido)
    k = r.cargar("opendss", tmp_path / "k")
    assert k["clases"]["Line"]["propiedades"]["length"] == ["1.2"]          # continuación ~
    assert k["clases"]["Transformer"]["propiedades"]["conns"] == ["(delta, wye)"]


def test_incremental_por_huella(tmp_path):
    assert _correr(tmp_path, "opendss", {"red.dss": DSS})
    assert _correr(tmp_path, "opendss", {"red.dss": DSS}) == {}               # sin cambios
    assert _correr(tmp_path, "opendss", {"red.dss": DSS + "New Capacitor.Q1 bus1=c kvar=10\n"})["opendss"] == ["Capacitor"]


def test_autocad_capas_y_bloques(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")

    def plano(ruta):
        doc = ezdxf.new()
        doc.layers.add("SIMBOLOS", color=5)
        b = doc.blocks.new("INTERRUPTOR_52")
        b.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True)
        b.add_attdef("TAG", (0, 1.2))
        doc.saveas(ruta)
    _correr(tmp_path, "autocad", {"plano.dxf": plano})
    k = r.cargar("autocad", tmp_path / "k")
    assert k["capas"]["SIMBOLOS"]["color"] == 5
    assert k["bloques"]["INTERRUPTOR_52"]["atributos"] == ["TAG"]


def test_powerfactory_dgs(tmp_path):
    _correr(tmp_path, "powerfactory", {"exporte.dgs": DGS})
    t = r.cargar("powerfactory", tmp_path / "k")["tablas"]
    assert t["ElmLne"]["columnas"] == ["ID", "loc_name", "dline", "bus1", "bus2"]


def test_etap_hojas_de_excel(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    def libro(ruta):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Buses"
        ws.append(["ID", "Nominal kV", "Type"])
        ws.append(["Bus1", 13.2, "SWNG"])
        wb.save(ruta)
    _correr(tmp_path, "etap", {"plantilla.xlsx": libro})
    t = r.cargar("etap", tmp_path / "k")["tablas"]["plantilla/Buses"]
    assert t["columnas"] == ["ID", "Nominal kV", "Type"] and t["muestra"] == ["Bus1", "13.2", "SWNG"]


def test_pvsyst_modulo(tmp_path):
    _correr(tmp_path, "pvsyst", {"modulo.PAN": PAN, "horas.csv": "Fecha;E_Grid;GlobInc\n01/01;10;300\n"})
    k = r.cargar("pvsyst", tmp_path / "k")
    assert k["objetos"]["modulo"]["parametros"]["PNom"] == ["550.0"]
    assert k["tablas"]["horas"]["columnas"] == ["Fecha", "E_Grid", "GlobInc"]


def test_archivo_danado_no_detiene_el_resto(tmp_path):
    res = _correr(tmp_path, "autocad", {"roto.dxf": "esto no es un dxf"})
    assert any("no se pudo leer" in x for x in res["autocad"])


def test_atpdraw_alimenta_el_catalogo(tmp_path, monkeypatch):
    import shutil

    from power_studies import atpdraw_catalogo as cat
    copia = tmp_path / "cat.json"
    shutil.copy(cat.RUTA, copia)
    monkeypatch.setattr(cat, "RUTA", copia)
    xml = ('<project Application="ATPDraw"><objects><comp Name="COMP_DE_PRUEBA"><comp_content PosX="0" PosY="0">'
           '<node Name="A" Value="" Kind="1" PosX="-20" PosY="0"/></comp_content></comp></objects></project>')
    assert _correr(tmp_path, "atpdraw", {"p.xml": xml})["atpdraw"] == ["COMP_DE_PRUEBA"]
    assert "COMP_DE_PRUEBA" in cat.cargar(copia)["componentes"]
