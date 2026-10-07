"""Validación de resultados contra la referencia guardada en el modelo
(p. ej. resultados originales de PowerFactory o un cálculo a mano)."""
from __future__ import annotations

from .modelo import Red
from .resultados import Resultados


def contra_referencia(red: Red, res: Resultados, tol_u_pu: float = 0.005,
                      tol_carga_pct: float = 2.0) -> tuple[bool, list[str]]:
    """Devuelve (coincide, líneas de detalle). Sin referencia -> (True, [aviso])."""
    ref = (red.referencia or {}).get(res.escenario)
    if not ref:
        return True, [f"sin referencia para el escenario '{res.escenario}'"]
    ok, det = True, []
    for bid, u_ref in (ref.get("u_pu") or {}).items():
        if bid not in res.barras:
            continue
        d = res.barras[bid].u_pu - u_ref
        bien = abs(d) <= tol_u_pu
        ok &= bien
        det.append(f"{'OK ' if bien else 'DIF'} u[{bid}] = {res.barras[bid].u_pu:.4f} (ref {u_ref:.4f}, Δ {d:+.4f})")
    for rid, c_ref in (ref.get("cargabilidad_pct") or {}).items():
        if rid not in res.ramas:
            continue
        d = res.ramas[rid].cargabilidad_pct - c_ref
        bien = abs(d) <= tol_carga_pct
        ok &= bien
        det.append(f"{'OK ' if bien else 'DIF'} carga[{rid}] = {res.ramas[rid].cargabilidad_pct:.1f} % "
                   f"(ref {c_ref:.1f} %, Δ {d:+.1f})")
    for rid, r in (ref.get("ramas") or {}).items():
        if rid not in res.ramas:
            continue
        rr = res.ramas[rid]
        if "i_A" in r:
            d =abs(rr.i_kA * 1000 - r["i_A"]) / r["i_A"] * 100
            bien = d <= 2.0
            ok &= bien
            det.append(f"{'OK ' if bien else 'DIF'} I[{rid}] = {rr.i_kA * 1000:.1f} A (ref {r['i_A']} A)")
    return ok, det
