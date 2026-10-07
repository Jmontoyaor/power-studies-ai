"""Formato común de resultados, igual para todas las herramientas."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ResBarra(BaseModel):
    u_pu: float
    ul_kV: float
    angulo_deg: float


class ResRama(BaseModel):
    p_MW: float = Field(description="Potencia activa en el extremo emisor (AT para trafos)")
    q_Mvar: float
    i_kA: float = Field(description="Corriente en el extremo emisor")
    i_kA_receptor: Optional[float] = None
    cargabilidad_pct: float
    perdidas_kW: float


class ResCortocircuito(BaseModel):
    ikss_kA: float
    skss_MVA: float
    ip_kA: Optional[float] = None


class Resultados(BaseModel):
    herramienta: str
    escenario: str
    convergio: bool
    iteraciones: Optional[int] = None
    barras: dict[str, ResBarra] = Field(default_factory=dict)
    ramas: dict[str, ResRama] = Field(default_factory=dict)
    cortocircuito: dict[str, ResCortocircuito] = Field(default_factory=dict)
    perdidas_totales_kW: Optional[float] = None
    notas: list[str] = Field(default_factory=list)

    def guardar(self, ruta: str | Path) -> None:
        Path(ruta).write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Resultados":
        return cls.model_validate(json.loads(Path(ruta).read_text(encoding="utf-8")))


def comparar(a: Resultados, b: Resultados, tol_u_pu: float = 0.005,
             tol_carga_pct: float = 2.0) -> list[str]:
    """Diferencias entre dos corridas (p. ej. pandapower vs PowerFactory).
    Devuelve una lista de discrepancias; vacía si coinciden dentro de tolerancia."""
    dif = []
    for bid, rb in a.barras.items():
        if bid in b.barras:
            d = abs(rb.u_pu - b.barras[bid].u_pu)
            if d > tol_u_pu:
                dif.append(f"barra {bid}: u {rb.u_pu:.4f} ({a.herramienta}) vs "
                           f"{b.barras[bid].u_pu:.4f} ({b.herramienta})")
    for rid, rr in a.ramas.items():
        if rid in b.ramas:
            d = abs(rr.cargabilidad_pct - b.ramas[rid].cargabilidad_pct)
            if d > tol_carga_pct:
                dif.append(f"rama {rid}: carga {rr.cargabilidad_pct:.1f}% vs "
                           f"{b.ramas[rid].cargabilidad_pct:.1f}%")
    return dif
