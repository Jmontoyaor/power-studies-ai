"""Configuraciones de barras de subestaciones: topología, confiabilidad y unifilar.

Cubre las configuraciones del syllabus (sección C):
    SBSB  barra sencilla                       (single bus single breaker)
    MTB   barra principal y de transferencia   (main and transfer bus)
    DBSB  doble barra con un interruptor       (double bus single breaker)
    BAH   interruptor y medio                  (breaker and a half)
    DBDB  doble barra con doble interruptor    (double bus double breaker)
    RB    anillo                               (ring bus)

Cada equipo de maniobra es una arista del grafo de la subestación, con su estado
normal (cerrado/abierto) y la geometría del dibujo. Con ese grafo se evalúan dos
contingencias clásicas para comparar configuraciones:

  * Falla en una barra: la protección diferencial de barras abre todo lo conectado a
    ella. Se pierden los circuitos que, en estado normal, solo llegaban al resto de la
    subestación a través de esa barra.
  * Mantenimiento de un interruptor: se permite maniobrar seccionadores (abrir y
    cerrar los normalmente abiertos). El circuito sigue en servicio si queda unido a
    otro circuito sin pasar por ese interruptor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import networkx as nx

CONFIGURACIONES = {
    "SBSB": "Barra sencilla",
    "MTB": "Barra principal y barra de transferencia",
    "DBSB": "Doble barra con un interruptor",
    "BAH": "Interruptor y medio",
    "DBDB": "Doble barra con doble interruptor",
    "RB": "Anillo",
}
Tipo = Literal["interruptor", "seccionador", "conductor"]


@dataclass
class Bahia:
    id: str
    tipo: Literal["linea", "transformador"] = "linea"
    nombre: str | None = None


@dataclass
class Subestacion:
    nombre: str
    tension_kV: float
    configuracion: str
    bahias: list[Bahia]


@dataclass
class Equipo:
    id: str
    tipo: Tipo
    n1: str
    n2: str
    p1: tuple[float, float]          # geometría para el dibujo
    p2: tuple[float, float]
    normalmente_cerrado: bool = True
    bahia: str | None = None
    puesta_tierra: bool = False      # seccionador con cuchilla de puesta a tierra (89T)


@dataclass
class Topologia:
    sub: Subestacion
    equipos: list[Equipo] = field(default_factory=list)
    barras: dict[str, tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=dict)
    circuitos: dict[str, tuple[float, float, str]] = field(default_factory=dict)  # id -> (x, y, dirección)

    # ---------------------------------------------------------------- conteos
    def interruptores(self) -> list[Equipo]:
        return [e for e in self.equipos if e.tipo == "interruptor"]

    def seccionadores(self) -> list[Equipo]:
        return [e for e in self.equipos if e.tipo == "seccionador"]

    # ---------------------------------------------------------------- grafo
    def grafo(self, incluir=lambda e: True) -> nx.MultiGraph:
        g = nx.MultiGraph()
        g.add_nodes_from(self.barras)
        g.add_nodes_from(self.circuitos)
        for e in self.equipos:
            if incluir(e):
                g.add_edge(e.n1, e.n2, id=e.id)
        return g

    def _unidos(self, g: nx.MultiGraph) -> set[str]:
        """Circuitos que siguen unidos a por lo menos otro circuito."""
        vivos = set()
        for c in self.circuitos:
            if c in g and any(o in g and o != c and nx.has_path(g, c, o) for o in self.circuitos):
                vivos.add(c)
        return vivos

    def perdidos_por_falla_en_barra(self, barra: str) -> set[str]:
        g = self.grafo(lambda e: e.normalmente_cerrado)
        g.remove_node(barra)
        return set(self.circuitos) - self._unidos(g)

    def perdidos_por_mantenimiento(self, interruptor: str) -> set[str]:
        g = self.grafo(lambda e: e.id != interruptor)
        return set(self.circuitos) - self._unidos(g)


# ------------------------------------------------------------------ constructor
W = 4.0   # separación horizontal entre bahías (deja espacio a la salida del circuito)


class _Armador:
    def __init__(self, sub: Subestacion):
        self.t = Topologia(sub)
        self.cuenta: dict[str, int] = {}

    def _id(self, prefijo: str) -> str:
        self.cuenta[prefijo] = self.cuenta.get(prefijo, 0) + 1
        return f"{prefijo}-{self.cuenta[prefijo]}"

    def eq(self, tipo: Tipo, n1, n2, p1, p2, bahia=None, nc=True, pt=False, prefijo=None):
        pre = prefijo or {"interruptor": "52", "seccionador": "89", "conductor": "W"}[tipo]
        e = Equipo(self._id(pre), tipo, n1, n2, p1, p2, nc, bahia, pt)
        self.t.equipos.append(e)
        return e

    def tramo(self, nodos, puntos, bahia, abiertos=(), pt_ultimo=False):
        """Cadena seccionador-interruptor-seccionador entre nodos[0] y nodos[-1]."""
        tipos = ["seccionador", "interruptor", "seccionador"]
        for i, tipo in enumerate(tipos):
            self.eq(tipo, nodos[i], nodos[i + 1], puntos[i], puntos[i + 1], bahia,
                    nc=i not in abiertos, pt=pt_ultimo and i == 2)


def armar(sub: Subestacion) -> Topologia:
    """Topología completa (equipos, barras y salidas de circuito) de la configuración."""
    conf = sub.configuracion.upper()
    if conf not in CONFIGURACIONES:
        raise ValueError(f"configuración '{sub.configuracion}' no soportada: {sorted(CONFIGURACIONES)}")
    n = len(sub.bahias)
    if n < 2:
        raise ValueError("se necesitan por lo menos 2 bahías")
    if conf == "BAH" and n % 2:
        raise ValueError("interruptor y medio: use un número par de circuitos (2 por diámetro)")
    a = _Armador(sub)
    t = a.t
    ancho = (n + 1) * W

    if conf in ("SBSB", "MTB"):
        t.barras["BP" if conf == "MTB" else "B1"] = ((-W / 2, 0), (ancho - W / 2, 0))
        bp = "BP" if conf == "MTB" else "B1"
        if conf == "MTB":
            t.barras["BT"] = ((-W / 2, -4), (ancho - W / 2, -4))
        for k, b in enumerate(sub.bahias):
            x = k * W
            c = b.id
            a.tramo([bp, f"{c}.a", f"{c}.b", c], [(x, 0), (x, -1), (x, -2), (x, -3)], c, pt_ultimo=True)
            t.circuitos[c] = (x, -3, "derecha")
            if conf == "MTB":  # seccionador de bypass a la barra de transferencia, normalmente abierto
                a.eq("seccionador", c, "BT", (x, -3), (x, -4), c, nc=False, prefijo="89BP")
        if conf == "MTB":  # bahía de transferencia (acople), normalmente abierta
            x = n * W
            a.tramo(["BP", "AT.a", "AT.b", "BT"], [(x, 0), (x, -1.3), (x, -2.7), (x, -4)], "ACOPLE",
                    abiertos=(1,))

    elif conf == "DBSB":
        t.barras["B1"] = ((-W / 2, 0), (ancho - W / 2, 0))
        t.barras["B2"] = ((-W / 2, -0.8), (ancho - W / 2, -0.8))
        for k, b in enumerate(sub.bahias):
            x, c = k * W, b.id
            en_b1 = k % 2 == 0  # circuitos repartidos entre las dos barras
            a.eq("seccionador", "B1", f"{c}.a", (x - 0.3, 0), (x - 0.3, -1.4), c, nc=en_b1, prefijo="89B1")
            a.eq("seccionador", "B2", f"{c}.a", (x + 0.3, -0.8), (x + 0.3, -1.4), c, nc=not en_b1, prefijo="89B2")
            a.eq("conductor", f"{c}.a", f"{c}.a", (x - 0.3, -1.4), (x + 0.3, -1.4), c)
            a.eq("interruptor", f"{c}.a", f"{c}.b", (x, -1.4), (x, -2.3), c)
            a.eq("seccionador", f"{c}.b", c, (x, -2.3), (x, -3.2), c, pt=True, prefijo="89L")
            t.circuitos[c] = (x, -3.2, "derecha")
        x = n * W  # acople de barras, normalmente cerrado
        a.eq("seccionador", "B1", "AC.a", (x - 0.3, 0), (x - 0.3, -1.4), "ACOPLE")
        a.eq("seccionador", "B2", "AC.b", (x + 0.3, -0.8), (x + 0.3, -1.4), "ACOPLE")
        a.eq("interruptor", "AC.a", "AC.b", (x - 0.3, -1.4), (x + 0.3, -1.4), "ACOPLE")

    elif conf == "DBDB":
        t.barras["B1"] = ((-W / 2, 0), (n * W - W / 2, 0))
        t.barras["B2"] = ((-W / 2, -6), (n * W - W / 2, -6))
        for k, b in enumerate(sub.bahias):
            x, c = k * W, b.id
            a.tramo(["B1", f"{c}.a", f"{c}.b", f"{c}.j"], [(x, 0), (x, -1), (x, -2), (x, -3)], c)
            a.tramo(["B2", f"{c}.d", f"{c}.c", f"{c}.j"], [(x, -6), (x, -5), (x, -4), (x, -3)], c)
            a.eq("seccionador", f"{c}.j", c, (x, -3), (x + 0.9, -3), c, pt=True, prefijo="89L")
            t.circuitos[c] = (x + 0.9, -3, "derecha")

    elif conf == "BAH":
        diam = n // 2
        t.barras["B1"] = ((-W / 2, 0), (diam * W - W / 2, 0))
        t.barras["B2"] = ((-W / 2, -9), (diam * W - W / 2, -9))
        for d in range(diam):
            x = d * W
            c1, c2 = sub.bahias[2 * d].id, sub.bahias[2 * d + 1].id
            dia = f"D{d + 1}"
            j1, j2 = f"{dia}.j1", f"{dia}.j2"
            a.tramo(["B1", f"{dia}.a", f"{dia}.b", j1], [(x, 0), (x, -1), (x, -2), (x, -3)], dia)
            a.tramo([j1, f"{dia}.c", f"{dia}.d", j2], [(x, -3), (x, -4), (x, -5), (x, -6)], dia)
            a.tramo([j2, f"{dia}.e", f"{dia}.f", "B2"], [(x, -6), (x, -7), (x, -8), (x, -9)], dia)
            for j, c, y in ((j1, c1, -3), (j2, c2, -6)):
                a.eq("seccionador", j, c, (x, y), (x + 0.9, y), c, pt=True, prefijo="89L")
                t.circuitos[c] = (x + 0.9, y, "derecha")

    else:  # RB
        r = max(2.0, n * W / (2 * math.pi) + 1)
        nodos = [f"R{i}" for i in range(n)]
        ang = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]
        pts = [(r * math.cos(q), r * math.sin(q)) for q in ang]
        for i in range(n):
            j = (i + 1) % n
            p, q = pts[i], pts[j]
            seg = [(p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f) for f in (0, 1 / 3, 2 / 3, 1)]
            a.tramo([nodos[i], f"R{i}.a", f"R{i}.b", nodos[j]], seg, f"ANILLO-{i + 1}")
        for i, b in enumerate(sub.bahias):
            p = pts[i]
            fuera = (p[0] * (1 + 1.6 / r), p[1] * (1 + 1.6 / r))
            a.eq("seccionador", nodos[i], b.id, p, fuera, b.id, pt=True, prefijo="89L")
            t.circuitos[b.id] = (fuera[0], fuera[1], "radial")
    return t


def interruptores_esperados(configuracion: str, n: int) -> float:
    """Número de interruptores de libro para n circuitos."""
    return {"SBSB": n, "MTB": n + 1, "DBSB": n + 1, "BAH": 1.5 * n, "DBDB": 2 * n, "RB": n}[configuracion.upper()]


def resumen_confiabilidad(t: Topologia) -> dict[str, object]:
    """Peor caso de cada contingencia, para comparar configuraciones."""
    n = len(t.circuitos)
    por_barra = {b: len(t.perdidos_por_falla_en_barra(b)) for b in t.barras}
    por_52 = {e.id: len(t.perdidos_por_mantenimiento(e.id)) for e in t.interruptores()}
    return {
        "configuracion": CONFIGURACIONES[t.sub.configuracion.upper()],
        "circuitos": n,
        "interruptores": len(t.interruptores()),
        "seccionadores": len(t.seccionadores()),
        "max_perdidos_falla_barra": max(por_barra.values(), default=0),
        "max_perdidos_mantenimiento_52": max(por_52.values(), default=0),
    }


# ------------------------------------------------------------------ dibujo
def dibujar(t: Topologia, ruta, titulo: str | None = None) -> list:
    """Unifilar de la subestación (PNG, SVG o PDF según la extensión; varias rutas separadas por coma).

    Símbolos: interruptor = cuadrado; seccionador = cuchilla (NA = normalmente abierto);
    puesta a tierra en el seccionador de salida; en cada salida TC, TP y pararrayos;
    flecha = línea, dos círculos = transformador."""
    import matplotlib

    matplotlib.use("Agg")
    from pathlib import Path

    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Rectangle

    fig, ax = plt.subplots(figsize=(max(8, 1.6 * len(t.circuitos) + 4), 9))
    ax.set_aspect("equal")
    ax.axis("off")
    c_linea, c_barra = "#263238", "#b71c1c"

    def seg(p, q, **kw):
        ax.plot([p[0], q[0]], [p[1], q[1]], color=kw.pop("color", c_linea), lw=kw.pop("lw", 1.4), **kw)

    def unitario(p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        largo = math.hypot(dx, dy) or 1.0
        return dx / largo, dy / largo, largo

    def tierra(p, ux, uy):
        nx_, ny_ = -uy, ux
        for i, ancho in enumerate((0.22, 0.14, 0.06)):
            c = (p[0] + ux * 0.06 * i, p[1] + uy * 0.06 * i)
            seg((c[0] - nx_ * ancho / 2, c[1] - ny_ * ancho / 2), (c[0] + nx_ * ancho / 2, c[1] + ny_ * ancho / 2), lw=1)

    for nombre, (p, q) in t.barras.items():
        seg(p, q, lw=4, color=c_barra)
        ax.text(p[0] - 0.15, p[1], nombre, ha="right", va="center", fontsize=10, fontweight="bold", color=c_barra)

    for e in t.equipos:
        ux, uy, largo = unitario(e.p1, e.p2)
        m = ((e.p1[0] + e.p2[0]) / 2, (e.p1[1] + e.p2[1]) / 2)
        if e.tipo == "conductor":
            seg(e.p1, e.p2)
            continue
        h = 0.18  # medio tamaño del símbolo
        a = (m[0] - ux * h, m[1] - uy * h)
        b = (m[0] + ux * h, m[1] + uy * h)
        seg(e.p1, a)
        seg(b, e.p2)
        if e.tipo == "interruptor":
            ax.add_patch(Rectangle((m[0] - h, m[1] - h), 2 * h, 2 * h, fill=e.normalmente_cerrado,
                                   facecolor="#455a64", edgecolor=c_linea, lw=1.4, zorder=3))
        else:  # seccionador: cuchilla girada 30° desde el borne a
            giro = math.radians(30 if e.normalmente_cerrado else 50)
            bx = ux * math.cos(giro) - uy * math.sin(giro)
            by = ux * math.sin(giro) + uy * math.cos(giro)
            seg(a, (a[0] + bx * 2 * h, a[1] + by * 2 * h))
            seg((b[0] - uy * 0.08, b[1] + ux * 0.08), (b[0] + uy * 0.08, b[1] - ux * 0.08))
            if not e.normalmente_cerrado:
                ax.text(m[0] + 0.25, m[1], "NA", fontsize=6, color="#6a1b9a", va="center")
            if e.puesta_tierra:  # 89T: cuchilla de puesta a tierra en el borne de salida
                base = (e.p2[0] - uy * 0.0, e.p2[1])
                pie = (base[0] + 0.0, base[1] - 0.55) if abs(uy) < 0.5 else (base[0] + 0.55, base[1])
                dx, dy, _ = unitario(base, pie)
                medio = (base[0] + dx * 0.2, base[1] + dy * 0.2)
                seg(base, medio, lw=1)
                seg(medio, (medio[0] + dx * 0.2 + dy * 0.12, medio[1] + dy * 0.2 - dx * 0.12), lw=1)
                seg((medio[0] + dx * 0.25, medio[1] + dy * 0.25), pie, lw=1)
                tierra(pie, dx, dy)
        if abs(ux) > 0.7:   # equipo horizontal: etiqueta arriba
            ax.text(m[0], m[1] + 0.32, e.id, fontsize=6, ha="center", va="bottom", color="#37474f")
        else:
            ax.text(m[0] - 0.28, m[1], e.id, fontsize=6, ha="right", va="center", color="#37474f")

    tipos = {b.id: b.tipo for b in t.sub.bahias}
    for c, (x, y, dirn) in t.circuitos.items():
        if dirn == "radial":
            ux, uy, _ = unitario((0, 0), (x, y))
        else:
            ux, uy = 1.0, 0.0
        tc = (x + ux * 0.45, y + uy * 0.45)
        seg((x, y), (x + ux * 1.6, y + uy * 1.6))
        for k in (0, 0.18):  # TC: dos anillos sobre el conductor
            ax.add_patch(Circle((tc[0] + ux * k, tc[1] + uy * k), 0.11, fill=False, lw=1, color=c_linea, zorder=3))
        tp = (x + ux * 0.95, y + uy * 0.95)  # TP y pararrayos en derivación
        nx_, ny_ = -uy, ux
        if abs(ny_) < 1e-9 and nx_ == 0:
            nx_, ny_ = 0.0, -1.0
        lado = (tp[0] - nx_ * 0.45 if dirn != "radial" else tp[0] + nx_ * 0.45,
                tp[1] - ny_ * 0.45 if dirn != "radial" else tp[1] + ny_ * 0.45)
        seg(tp, lado, lw=1)
        ax.add_patch(Circle(lado, 0.09, fill=False, lw=1, color=c_linea))
        ax.add_patch(Circle((lado[0] + 0.1, lado[1]), 0.09, fill=False, lw=1, color=c_linea))
        pr = (x + ux * 1.35, y + uy * 1.35)  # pararrayos: derivación a tierra con elemento resistivo
        ext = (pr[0] + nx_ * 0.55 if dirn == "radial" else pr[0], pr[1] + ny_ * 0.55 if dirn == "radial" else pr[1] + 0.55)
        dx, dy, _ = unitario(pr, ext)
        seg(pr, (pr[0] + dx * 0.15, pr[1] + dy * 0.15), lw=1)
        ax.add_patch(Rectangle((pr[0] + dx * 0.15 - 0.06 - dy * 0.0, pr[1] + dy * 0.15 - (0.06 if abs(dx) > 0.5 else 0.0)),
                               0.12 if abs(dy) > 0.5 else 0.25, 0.25 if abs(dy) > 0.5 else 0.12,
                               fill=False, lw=1, color=c_linea))
        seg((pr[0] + dx * 0.4, pr[1] + dy * 0.4), ext, lw=1)
        tierra(ext, dx, dy)
        fin = (x + ux * 1.6, y + uy * 1.6)
        if tipos.get(c) == "transformador":
            ax.add_patch(Circle((fin[0] + ux * 0.2, fin[1] + uy * 0.2), 0.2, fill=False, lw=1.4, color=c_linea))
            ax.add_patch(Circle((fin[0] + ux * 0.48, fin[1] + uy * 0.48), 0.2, fill=False, lw=1.4, color=c_linea))
            etq = (fin[0] + ux * 1.25, fin[1] + uy * 1.25 - (0.25 if uy < -0.5 else 0.0))
        else:
            ax.annotate("", xy=(fin[0] + ux * 0.4, fin[1] + uy * 0.4), xytext=fin,
                        arrowprops=dict(arrowstyle="-|>", color=c_linea, lw=1.4))
            etq = (fin[0] + ux * 0.75, fin[1] + uy * 0.75)
        ax.text(etq[0], etq[1] + 0.2, c, fontsize=8, ha="center", fontweight="bold")

    ax.set_title(titulo or f"{t.sub.nombre} — {CONFIGURACIONES[t.sub.configuracion.upper()]} — {t.sub.tension_kV:g} kV",
                 fontsize=11)
    ax.text(0.01, 0.01, "52 interruptor · 89 seccionador (NA: normalmente abierto) · 89L con cuchilla de puesta a tierra · TC, TP y pararrayos en cada salida",
            transform=ax.transAxes, fontsize=7, color="#546e7a")
    ax.autoscale_view()
    ax.margins(0.08)
    rutas = []
    for r in str(ruta).split(","):
        r = Path(r.strip())
        r.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(r, dpi=160, bbox_inches="tight")
        rutas.append(r)
    plt.close(fig)
    return rutas
