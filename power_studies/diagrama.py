"""Diagrama unifilar: posiciones automáticas y dibujo con resultados.

1. `auto_layout(red)` calcula la posición de cada barra a partir de la
   topología (árbol desde la barra slack) y la guarda en `Barra.pos`. Esas
   mismas posiciones las usan los adaptadores para dibujar el unifilar
   dentro de cada herramienta (PowerFactory, ATPDraw, ...).
2. `dibujar(red, resultados)` produce un unifilar propio (SVG/PNG) con los
   resultados encima, igual para cualquier herramienta: sirve para el
   informe y para comparar herramientas lado a lado.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
from matplotlib.patches import Circle, FancyArrow, Rectangle  # noqa: E402

from .modelo import Posicion, Red  # noqa: E402
from .resultados import Resultados  # noqa: E402

DX = 80.0   # separación horizontal entre ramas (mm)
DY = 60.0   # separación vertical entre niveles (mm)

COLOR_OK = "#2e7d32"
COLOR_ALERTA = "#ef6c00"
COLOR_FALLA = "#c62828"
COLOR_LINEA = "#37474f"


def grafo(red: Red) -> nx.Graph:
    g = nx.Graph()
    g.add_nodes_from(b.id for b in red.barras)
    for rid, a, b, obj in red.ramas():
        g.add_edge(a, b, id=rid, obj=obj)
    return g


def auto_layout(red: Red, sobrescribir: bool = False) -> Red:
    """Asigna posiciones (x, y) en mm a las barras: árbol de arriba hacia abajo."""
    g = grafo(red)
    raiz = red.redes_externas[0].barra
    visit = set()
    # para redes malladas usamos el árbol de expansión BFS
    arbol = nx.bfs_tree(g, raiz)
    for comp in nx.connected_components(g):
        if raiz not in comp:
            otra = sorted(comp)[0]
            arbol = nx.compose(arbol, nx.bfs_tree(g.subgraph(comp), otra))

    hojas: dict[str, int] = {}

    def contar(n):
        hijos = list(arbol.successors(n))
        hojas[n] = sum(contar(h) for h in hijos) if hijos else 1
        return hojas[n]

    raices = [n for n in arbol.nodes if arbol.in_degree(n) == 0]
    for r in raices:
        contar(r)

    pos: dict[str, tuple[float, float]] = {}

    def ubicar(n, x0, nivel):
        visit.add(n)
        ancho = hojas[n] * DX
        pos[n] = (x0 + ancho / 2, -nivel * DY)
        x = x0
        for h in sorted(arbol.successors(n)):
            ubicar(h, x, nivel + 1)
            x += hojas[h] * DX

    x = 0.0
    for r in raices:
        ubicar(r, x, 0)
        x += hojas[r] * DX

    for b in red.barras:
        if sobrescribir or b.pos is None:
            px, py = pos[b.id]
            b.pos = Posicion(x=round(px, 1), y=round(py, 1))
    return red


def _color_carga(pct: float, red: Red) -> str:
    c = red.criterios
    if pct > c.cargabilidad_max_pct:
        return COLOR_FALLA
    if pct >= c.cargabilidad_alerta_pct:
        return COLOR_ALERTA
    return COLOR_OK


def _color_tension(u: float, red: Red) -> str:
    c = red.criterios
    return COLOR_OK if c.u_min_pu <= u <= c.u_max_pu else COLOR_FALLA


def dibujar(red: Red, res: Resultados | None = None, salida: str | Path | None = None,
            titulo: str | None = None) -> list[Path]:
    """Dibuja el unifilar. Devuelve las rutas escritas (.svg y .png)."""
    auto_layout(red)
    P = {b.id: (b.pos.x, b.pos.y) for b in red.barras}
    xs = [p[0] for p in P.values()]
    ys = [p[1] for p in P.values()]
    ancho = max(xs) - min(xs) + 2 * DX
    alto = max(ys) - min(ys) + 2.2 * DY
    fig, ax = plt.subplots(figsize=(max(6, ancho / 28), max(6, alto / 28)))
    ax.set_aspect("equal")
    ax.axis("off")
    L = 26  # semiancho del barraje

    # ramas
    for rid, a, b, obj in red.ramas():
        (xa, ya), (xb, yb) = P[a], P[b]
        rr = res.ramas.get(rid) if res else None
        col = _color_carga(rr.cargabilidad_pct, red) if rr else COLOR_LINEA
        ax.plot([xa, xa, xb, xb], [ya, (ya + yb) / 2, (ya + yb) / 2, yb], color=col, lw=2, zorder=1)
        xm, ym = xb, (ya + yb) / 2
        es_trafo = hasattr(obj, "sn_MVA")
        if es_trafo:
            ax.add_patch(Circle((xm, ym + 4.5), 6.5, fill=False, lw=1.8, ec=col, zorder=3))
            ax.add_patch(Circle((xm, ym - 4.5), 6.5, fill=False, lw=1.8, ec=col, zorder=3))
            ax.add_patch(Circle((xm, ym + 4.5), 6.4, fc="white", ec="none", zorder=2))
            ax.add_patch(Circle((xm, ym - 4.5), 6.4, fc="white", ec="none", zorder=2))
            txt = f"{obj.etiqueta}\n{obj.sn_MVA * 1000:g} kVA {obj.grupo}\nuk {obj.uk_pct:g} %"
        else:
            txt = f"{obj.etiqueta}\n{obj.conductor or ''}\n{obj.longitud_km * 1000:g} m".replace("\n\n", "\n")
        if rr:
            txt += f"\n{rr.cargabilidad_pct:.1f} %  ({rr.i_kA_receptor * 1000 if rr.i_kA_receptor else rr.i_kA * 1000:.1f} A)"
        ax.text(xm + 11, ym, txt, fontsize=7, va="center", ha="left", color=col)

    # barras
    for b in red.barras:
        x, y = P[b.id]
        rb = res.barras.get(b.id) if res else None
        col = _color_tension(rb.u_pu, red) if rb else "black"
        ax.plot([x - L, x + L], [y, y], color=col, lw=5, solid_capstyle="butt", zorder=4)
        ax.text(x - L - 2, y, b.etiqueta, fontsize=8, ha="right", va="center", weight="bold")
        info = f"{b.un_kV:g} kV"
        if rb:
            info = f"{rb.ul_kV:.3f} kV | {rb.u_pu:.4f} p.u. | {rb.angulo_deg:.1f}°"
        ax.text(x - L - 2, y - 7, info, fontsize=6.5, ha="right", va="center", color=col)

    # red externa
    for xn in red.redes_externas:
        x, y = P[xn.barra]
        ax.plot([x, x], [y, y + 14], color="black", lw=1.5)
        ax.add_patch(Rectangle((x - 9, y + 14), 18, 12, fill=False, hatch="////", lw=1.5))
        ax.text(x + 12, y + 20, f"{xn.etiqueta}\nScc {xn.scc_max_MVA:g} MVA", fontsize=7, va="center")

    # cargas y generación (debajo de su barra, desplazadas)
    usados: dict[str, int] = {}
    for c in red.cargas + red.generadores_pv:
        x, y = P[c.barra]
        k = usados.get(c.barra, 0)
        usados[c.barra] = k + 1
        xc = x - L + 8 + 14 * k
        ax.plot([xc, xc], [y, y - 12], color="black", lw=1.5)
        if hasattr(c, "sn_MVA"):
            ax.add_patch(Rectangle((xc - 6, y - 24), 12, 12, fill=False, lw=1.5))
            ax.text(xc, y - 18, "PV", fontsize=6, ha="center", va="center")
            lab = f"{c.etiqueta}\n{c.p_MW * 1000:g} kW"
        else:
            ax.add_patch(FancyArrow(xc, y - 12, 0, -8, width=0.4, head_width=6, head_length=6,
                                    color="black", length_includes_head=True))
            lab = f"{c.etiqueta}\n{c.p_MW * 1000:.1f} kW\n{c.q_Mvar * 1000:.1f} kvar"
        ax.text(xc, y - 30, lab, fontsize=6.5, ha="center", va="top")

    tit = titulo or red.proyecto
    if res:
        tit += f"\nFlujo de cargas — {res.herramienta} — escenario {res.escenario}"
    ax.set_title(tit, fontsize=10)
    ax.set_xlim(min(xs) - DX * 1.6, max(xs) + DX * 1.3)
    ax.set_ylim(min(ys) - DY * 1.1, max(ys) + DY * 0.8)
    leyenda = [plt.Line2D([], [], color=COLOR_OK, lw=3, label="Cumple"),
               plt.Line2D([], [], color=COLOR_ALERTA, lw=3, label=f"≥ {red.criterios.cargabilidad_alerta_pct:g} % carga"),
               plt.Line2D([], [], color=COLOR_FALLA, lw=3, label="No cumple")]
    if res:
        ax.legend(handles=leyenda, loc="lower right", fontsize=7, frameon=False)
    rutas = []
    if salida:
        salida = Path(salida)
        salida.parent.mkdir(parents=True, exist_ok=True)
        for ext in (".svg", ".png"):
            r = salida.with_suffix(ext)
            fig.savefig(r, dpi=200, bbox_inches="tight")
            rutas.append(r)
    plt.close(fig)
    return rutas
