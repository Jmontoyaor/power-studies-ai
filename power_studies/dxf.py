"""Exportación a DXF (AutoCAD) de los planos del estudio. Requiere `ezdxf` (pip install ezdxf).

- `unifilar_subestacion`: el unifilar de `subestacion.armar`, con la misma geometría
  del PNG, en capas BARRAS, EQUIPOS, CONDUCTORES, SALIDAS y TEXTOS.
- `planta_malla`: la planta de la malla de puesta a tierra a escala real (metros), en
  capas MALLA, VARILLAS, COTAS y TEXTOS, con el cuadro de resultados de IEEE 80.

AutoCAD no es necesario para generar los archivos, solo para abrirlos.
"""
from __future__ import annotations

import math
from pathlib import Path

from .puesta_tierra import Malla, Resultado
from .subestacion import CONFIGURACIONES, Topologia

ESCALA = 10.0  # unidades de dibujo por unidad del esquema del unifilar


def _doc(capas: dict[str, int], unidades: int):
    try:
        import ezdxf
    except ImportError as e:  # pragma: no cover
        raise ImportError("instale ezdxf para exportar a AutoCAD: pip install ezdxf") from e
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = unidades  # 6 = metros; 0 = sin unidades
    for nombre, color in capas.items():
        doc.layers.add(nombre, color=color)
    return doc, doc.modelspace()


def _texto(msp, s: str, p, altura: float, capa: str = "TEXTOS", alinear: str = "MIDDLE_CENTER"):
    from ezdxf.enums import TextEntityAlignment
    msp.add_text(s, height=altura, dxfattribs={"layer": capa}).set_placement(
        p, align=getattr(TextEntityAlignment, alinear))


def _tierra(msp, p, ux, uy, capa):
    nx_, ny_ = -uy, ux
    for i, ancho in enumerate((2.2, 1.4, 0.6)):
        c = (p[0] + ux * 0.6 * i, p[1] + uy * 0.6 * i)
        msp.add_line((c[0] - nx_ * ancho / 2, c[1] - ny_ * ancho / 2),
                     (c[0] + nx_ * ancho / 2, c[1] + ny_ * ancho / 2), dxfattribs={"layer": capa})


def unifilar_subestacion(t: Topologia, ruta: str | Path) -> Path:
    """Unifilar de la subestación en DXF (esquemático, sin unidades físicas)."""
    doc, msp = _doc({"BARRAS": 1, "EQUIPOS": 5, "CONDUCTORES": 7, "SALIDAS": 3, "TEXTOS": 8}, 0)
    k = ESCALA

    def P(p):
        return (p[0] * k, p[1] * k)

    def linea(p, q, capa="CONDUCTORES"):
        msp.add_line(p, q, dxfattribs={"layer": capa})

    for nombre, (p, q) in t.barras.items():
        msp.add_lwpolyline([P(p), P(q)], dxfattribs={"layer": "BARRAS", "const_width": 0.8})
        _texto(msp, nombre, (P(p)[0] - 2, P(p)[1]), 2.0, alinear="MIDDLE_RIGHT")

    for e in t.equipos:
        p, q = P(e.p1), P(e.p2)
        dx, dy = q[0] - p[0], q[1] - p[1]
        largo = math.hypot(dx, dy) or 1.0
        ux, uy = dx / largo, dy / largo
        if e.tipo == "conductor":
            linea(p, q)
            continue
        m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        h = 1.8
        a = (m[0] - ux * h, m[1] - uy * h)
        b = (m[0] + ux * h, m[1] + uy * h)
        linea(p, a)
        linea(b, q)
        if e.tipo == "interruptor":
            cuadro = [(m[0] - h, m[1] - h), (m[0] + h, m[1] - h), (m[0] + h, m[1] + h), (m[0] - h, m[1] + h)]
            msp.add_lwpolyline(cuadro, close=True, dxfattribs={"layer": "EQUIPOS"})
            if e.normalmente_cerrado:
                hatch = msp.add_hatch(color=5, dxfattribs={"layer": "EQUIPOS"})
                hatch.paths.add_polyline_path(cuadro, is_closed=True)
        else:
            giro = math.radians(30 if e.normalmente_cerrado else 50)
            bx = ux * math.cos(giro) - uy * math.sin(giro)
            by = ux * math.sin(giro) + uy * math.cos(giro)
            linea(a, (a[0] + bx * 2 * h, a[1] + by * 2 * h), "EQUIPOS")
            linea((b[0] - uy * 0.8, b[1] + ux * 0.8), (b[0] + uy * 0.8, b[1] - ux * 0.8), "EQUIPOS")
            if not e.normalmente_cerrado:
                _texto(msp, "NA", (m[0] + 3, m[1]), 1.0)
            if e.puesta_tierra:  # 89T hacia abajo (salida vertical) o a la derecha (horizontal)
                pie = (q[0], q[1] - 5.5) if abs(uy) < 0.5 else (q[0] + 5.5, q[1])
                fx, fy = (pie[0] - q[0]) / 5.5, (pie[1] - q[1]) / 5.5
                medio = (q[0] + fx * 2, q[1] + fy * 2)
                linea(q, medio, "EQUIPOS")
                linea(medio, (medio[0] + fx * 2 + fy * 1.2, medio[1] + fy * 2 - fx * 1.2), "EQUIPOS")
                linea((medio[0] + fx * 2.5, medio[1] + fy * 2.5), pie, "EQUIPOS")
                _tierra(msp, pie, fx, fy, "EQUIPOS")
        horizontal = abs(ux) > 0.7
        _texto(msp, e.id, (m[0], m[1] + 3.2) if horizontal else (m[0] - 2.8, m[1]), 0.9,
               alinear="BOTTOM_CENTER" if horizontal else "MIDDLE_RIGHT")

    tipos = {b.id: b.tipo for b in t.sub.bahias}
    for c, (x, y, dirn) in t.circuitos.items():
        if dirn == "radial":
            r = math.hypot(x, y) or 1.0
            ux, uy = x / r, y / r
        else:
            ux, uy = 1.0, 0.0
        o = P((x, y))
        fin = (o[0] + ux * 16, o[1] + uy * 16)
        linea(o, fin, "SALIDAS")
        for d in (4.5, 6.3):  # TC
            msp.add_circle((o[0] + ux * d, o[1] + uy * d), 1.1, dxfattribs={"layer": "SALIDAS"})
        nx_, ny_ = (-uy, ux) if dirn == "radial" else (0.0, -1.0)
        tp = (o[0] + ux * 9.5, o[1] + uy * 9.5)  # TP
        lado = (tp[0] + nx_ * 4.5, tp[1] + ny_ * 4.5)
        linea(tp, lado, "SALIDAS")
        msp.add_circle(lado, 0.9, dxfattribs={"layer": "SALIDAS"})
        msp.add_circle((lado[0] + ux * 1.0, lado[1] + uy * 1.0), 0.9, dxfattribs={"layer": "SALIDAS"})
        pr = (o[0] + ux * 13.5, o[1] + uy * 13.5)  # pararrayos
        ext = (pr[0] - nx_ * 5.5, pr[1] - ny_ * 5.5)
        linea(pr, (pr[0] - nx_ * 1.5, pr[1] - ny_ * 1.5), "SALIDAS")
        c0 = (pr[0] - nx_ * 1.5, pr[1] - ny_ * 1.5)
        c1 = (pr[0] - nx_ * 4.0, pr[1] - ny_ * 4.0)
        msp.add_lwpolyline([(c0[0] - ux * 0.6, c0[1] - uy * 0.6), (c0[0] + ux * 0.6, c0[1] + uy * 0.6),
                            (c1[0] + ux * 0.6, c1[1] + uy * 0.6), (c1[0] - ux * 0.6, c1[1] - uy * 0.6)],
                           close=True, dxfattribs={"layer": "SALIDAS"})
        linea(c1, ext, "SALIDAS")
        _tierra(msp, ext, -nx_, -ny_, "SALIDAS")
        if tipos.get(c) == "transformador":
            msp.add_circle((fin[0] + ux * 2, fin[1] + uy * 2), 2.0, dxfattribs={"layer": "SALIDAS"})
            msp.add_circle((fin[0] + ux * 4.8, fin[1] + uy * 4.8), 2.0, dxfattribs={"layer": "SALIDAS"})
            etq = (fin[0] + ux * 10, fin[1] + uy * 10)
        else:
            punta = (fin[0] + ux * 4, fin[1] + uy * 4)
            msp.add_lwpolyline([punta, (fin[0] - uy * 1.2, fin[1] + ux * 1.2), (fin[0] + uy * 1.2, fin[1] - ux * 1.2)],
                               close=True, dxfattribs={"layer": "SALIDAS"})
            etq = (fin[0] + ux * 8, fin[1] + uy * 8)
        _texto(msp, c, etq, 1.8)

    ymin = min(min(e.p1[1], e.p2[1]) for e in t.equipos) * k - 25
    xmin = min(min(e.p1[0], e.p2[0]) for e in t.equipos) * k
    _texto(msp, f"{t.sub.nombre} - {CONFIGURACIONES[t.sub.configuracion.upper()]} - {t.sub.tension_kV:g} kV",
           (xmin, ymin), 2.5, alinear="BOTTOM_LEFT")
    _texto(msp, "52 interruptor (relleno: cerrado) - 89 seccionador (NA: normalmente abierto) - "
                "89L con puesta a tierra - TC, TP y pararrayos en cada salida", (xmin, ymin - 4), 1.2,
           alinear="BOTTOM_LEFT")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(ruta)
    return ruta


def posiciones_varillas(m: Malla) -> list[tuple[float, float]]:
    """Varillas repartidas a lo largo del perímetro, empezando por las esquinas."""
    if m.n_varillas <= 0:
        return []
    esquinas = [(0.0, 0.0), (m.lx, 0.0), (m.lx, m.ly), (0.0, m.ly)]
    if m.n_varillas <= 4:
        return esquinas[: m.n_varillas]
    perimetro = 2 * (m.lx + m.ly)
    paso = perimetro / m.n_varillas
    puntos = []
    for i in range(m.n_varillas):
        s = i * paso
        for (x0, y0), (x1, y1) in zip(esquinas, esquinas[1:] + esquinas[:1]):
            lado = math.hypot(x1 - x0, y1 - y0)
            if s <= lado + 1e-9:
                f = s / lado
                puntos.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
                break
            s -= lado
    return puntos


def planta_malla(m: Malla, ruta: str | Path, resultado: Resultado | None = None,
                 titulo: str = "Malla de puesta a tierra") -> Path:
    """Planta de la malla a escala real (1 unidad = 1 m) con cuadro de resultados IEEE 80."""
    doc, msp = _doc({"MALLA": 30, "VARILLAS": 1, "COTAS": 3, "TEXTOS": 7}, 6)
    for i in range(m.nx):  # conductores paralelos al eje x
        y = i * m.ly / (m.nx - 1)
        msp.add_line((0, y), (m.lx, y), dxfattribs={"layer": "MALLA"})
    for j in range(m.ny):  # conductores paralelos al eje y
        x = j * m.lx / (m.ny - 1)
        msp.add_line((x, 0), (x, m.ly), dxfattribs={"layer": "MALLA"})
    r = max(0.25, min(m.lx, m.ly) / 120)
    for x, y in posiciones_varillas(m):
        msp.add_circle((x, y), r, dxfattribs={"layer": "VARILLAS"})
        msp.add_line((x - r, y - r), (x + r, y + r), dxfattribs={"layer": "VARILLAS"})
        msp.add_line((x - r, y + r), (x + r, y - r), dxfattribs={"layer": "VARILLAS"})
    t = max(0.6, min(m.lx, m.ly) / 45)  # altura de texto proporcional
    cota_y = -3 * t
    estilo = {"dimtxt": t, "dimasz": t * 0.8, "dimexe": t * 0.3, "dimexo": t * 0.3}
    msp.add_linear_dim(base=(0, cota_y), p1=(0, 0), p2=(m.lx, 0), override=estilo,
                       dxfattribs={"layer": "COTAS"}).render()
    msp.add_linear_dim(base=(-3 * t, 0), p1=(0, 0), p2=(0, m.ly), angle=90, override=estilo,
                       dxfattribs={"layer": "COTAS"}).render()
    lineas = [titulo,
              f"Malla {m.lx:g} m x {m.ly:g} m - {m.nx} x {m.ny} conductores - D = {m.espaciamiento:.2f} m",
              f"Profundidad h = {m.h:g} m - diámetro del conductor d = {m.d * 1000:.1f} mm - LC = {m.lc:.0f} m",
              f"Varillas: {m.n_varillas} de {m.l_varilla:g} m (LR = {m.lr:.0f} m)"]
    if resultado is not None:
        lineas += [f"Rg = {resultado.rg:.3f} ohm - GPR = {resultado.gpr:.0f} V - IG = {resultado.ig:.0f} A",
                   f"Em = {resultado.em:.1f} V (toque tolerable {resultado.e_toque_tol:.1f} V) - "
                   f"{'CUMPLE' if resultado.cumple_toque else 'NO CUMPLE'}",
                   f"Es = {resultado.es:.1f} V (paso tolerable {resultado.e_paso_tol:.1f} V) - "
                   f"{'CUMPLE' if resultado.cumple_paso else 'NO CUMPLE'}",
                   f"Sección mínima del conductor: {resultado.seccion_min_mm2:.1f} mm2 - cálculo IEEE Std 80-2013"]
    x0 = m.lx + 4 * t
    for i, s in enumerate(lineas):
        _texto(msp, s, (x0, m.ly - i * 1.8 * t), t * (1.3 if i == 0 else 1.0), alinear="TOP_LEFT")
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(ruta)
    return ruta
