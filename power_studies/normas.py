"""Verificación normativa automática (práctica colombiana por defecto).

Los límites salen de `Red.criterios`, así que se ajustan por proyecto u
operador de red sin tocar código.
  - NTC 1340: banda de tensión en estado estable (+5 % / -10 %).
  - NTC 2050 210.19(A) / 215.2(A) (notas informativas): caída <= 3 % por
    alimentador de BT y <= 5 % acumulada desde la barra de MT.
  - Cargabilidad de transformadores y conductores (NTC 2050 Tabla 310.15(B)(16)).
"""
from __future__ import annotations

from typing import Literal

import networkx as nx
from pydantic import BaseModel

from .diagrama import grafo
from .modelo import Red
from .resultados import Resultados

Estado = Literal["cumple", "alerta", "no cumple"]


class Verificacion(BaseModel):
    criterio: str
    norma: str
    elemento: str
    valor: float
    limite: str
    unidad: str
    estado: Estado


def verificar(red: Red, res: Resultados) -> list[Verificacion]:
    c = red.criterios
    out: list[Verificacion] = []
    margen = 0.2  # % o p.u.*100 de margen para marcar "alerta" (en el límite)

    # --- tensiones ---
    for b in red.barras:
        rb = res.barras.get(b.id)
        if not rb:
            continue
        u = rb.u_pu
        if c.u_min_pu <= u <= c.u_max_pu:
            cerca = min(u - c.u_min_pu, c.u_max_pu - u) * 100 < margen
            est = "alerta" if cerca else "cumple"
        else:
            est = "no cumple"
        out.append(Verificacion(criterio="Tensión en barra", norma="NTC 1340", elemento=b.etiqueta,
                                valor=round(u, 4), limite=f"{c.u_min_pu:.2f} a {c.u_max_pu:.2f}",
                                unidad="p.u.", estado=est))

    # --- caída en alimentadores de BT ---
    for l in red.lineas:
        if red.barra(l.desde).un_kV > 1.0:
            continue
        a, b = res.barras.get(l.desde), res.barras.get(l.hasta)
        if not (a and b):
            continue
        caida = abs(a.u_pu - b.u_pu) * 100
        out.append(_limite("Caída en alimentador BT", "NTC 2050 215.2(A) nota", l.etiqueta,
                           caida, c.caida_alimentador_pct, "%", margen))

    # --- caída acumulada desde la barra de MT (lado AT del trafo) ---
    g = grafo(red)
    for t in red.transformadores:
        u_at = res.barras.get(t.barra_at)
        if not u_at:
            continue
        g_bt = g.copy()
        g_bt.remove_edge(t.barra_at, t.barra_bt)
        aguas_abajo = nx.node_connected_component(g_bt, t.barra_bt)
        peor = None
        for bid in aguas_abajo:
            rb = res.barras.get(bid)
            if rb and red.barra(bid).un_kV <= 1.0:
                caida = (u_at.u_pu - rb.u_pu) * 100
                if peor is None or caida > peor[1]:
                    peor = (bid, caida)
        if peor:
            out.append(_limite("Caída acumulada MT → carga más lejana", "NTC 2050 210.19(A) nota",
                               f"{red.barra(t.barra_at).etiqueta} → {red.barra(peor[0]).etiqueta}",
                               peor[1], c.caida_total_pct, "%", margen))

    # --- cargabilidad ---
    for rid, _, _, obj in red.ramas():
        rr = res.ramas.get(rid)
        if not rr:
            continue
        pct = rr.cargabilidad_pct
        if pct > c.cargabilidad_max_pct:
            est = "no cumple"
        elif pct >= c.cargabilidad_alerta_pct:
            est = "alerta"
        else:
            est = "cumple"
        tipo = "transformador" if hasattr(obj, "sn_MVA") else "conductor"
        out.append(Verificacion(criterio=f"Cargabilidad de {tipo}",
                                norma="NTC 2050 Tabla 310.15(B)(16)" if tipo == "conductor" else "NTC 818/819",
                                elemento=obj.etiqueta, valor=round(pct, 1),
                                limite=f"≤ {c.cargabilidad_max_pct:g}", unidad="%", estado=est))
    return out


def _limite(criterio, norma, elemento, valor, limite, unidad, margen) -> Verificacion:
    if valor > limite:
        est = "no cumple"
    elif limite - valor < margen:
        est = "alerta"
    else:
        est = "cumple"
    return Verificacion(criterio=criterio, norma=norma, elemento=elemento, valor=round(valor, 2),
                        limite=f"≤ {limite:g}", unidad=unidad, estado=est)


def resumen(verifs: list[Verificacion]) -> dict[str, int]:
    r = {"cumple": 0, "alerta": 0, "no cumple": 0}
    for v in verifs:
        r[v.estado] += 1
    return r
