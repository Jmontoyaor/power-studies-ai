"""Informe técnico en LaTeX (y PDF) con memorias de cálculo.

Entrada: un manifiesto `estudio.yaml` que dice qué insumos tiene el estudio:

    titulo: Estudio eléctrico de la subestación X
    autor: Nombre del ingeniero
    red: red.yaml                 # flujo de cargas y verificación normativa
    escenarios: todos             # o una lista
    cortocircuito: true           # trifásica IEC 60909
    fallas: [1f, 2f]              # asimétricas IEC 60909
    malla: malla.yaml             # memoria IEEE 80
    baterias: baterias.yaml       # memoria IEEE 485 (+ cargador IEEE 946)
    subestacion: subestacion.yaml # unifilar y confiabilidad de la configuración
    textos: textos.yaml           # introduccion / analisis / conclusiones (agente redactor)

`planificar` decide con reglas explícitas qué secciones y anexos lleva el informe y
deja escrita la razón de cada decisión (sección "Alcance"). Los números salen del
código validado; el texto libre, si lo hay, lo aporta el agente redactor.
"""
from __future__ import annotations

import datetime as dt
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ------------------------------------------------------------------ utilidades LaTeX
_ESCAPES = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
            "Ω": r"$\Omega$", "ρ": r"$\rho$", "·": r"$\cdot$", "≈": r"$\approx$", "≤": r"$\leq$",
            "≥": r"$\geq$", "→": r"$\rightarrow$", "Δ": r"$\Delta$", "±": r"$\pm$"}


def esc(s) -> str:
    """Escapa texto para LaTeX."""
    return "".join(_ESCAPES.get(ch, ch) for ch in str(s))


def num(x: float, n: int = 2) -> str:
    """Número con coma decimal y separador de miles (formato colombiano)."""
    s = f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def nm(x: float, n: int = 2) -> str:
    """Como `num`, pero para modo matemático (la coma decimal va entre llaves)."""
    return num(x, n).replace(",", "{,}")


def tabla(encabezados: list[str], filas: list[list], alineacion: str | None = None, titulo: str | None = None) -> str:
    al = alineacion or ("l" + "r" * (len(encabezados) - 1))
    out = [r"\begingroup\small", r"\begin{longtable}{" + al + "}"]
    if titulo:
        out.append(r"\caption{" + esc(titulo) + r"}\\")
    out += [r"\toprule", " & ".join(r"\textbf{" + esc(h) + "}" for h in encabezados) + r" \\",
            r"\midrule", r"\endhead"]
    for f in filas:
        out.append(" & ".join(c if isinstance(c, Crudo) else esc(c) for c in f) + r" \\")
    out += [r"\bottomrule", r"\end{longtable}", r"\endgroup"]
    return "\n".join(out)


class Crudo(str):
    """Texto que ya es LaTeX y no debe escaparse."""


def estado(ok: bool) -> Crudo:
    return Crudo(r"\textcolor{ok}{CUMPLE}" if ok else r"\textcolor{mal}{\textbf{NO CUMPLE}}")


# ------------------------------------------------------------------ planificación
@dataclass
class Plan:
    secciones: list[str] = field(default_factory=list)
    anexos: list[str] = field(default_factory=list)
    razones: list[str] = field(default_factory=list)

    def agregar(self, seccion: str, razon: str, anexo: bool = False):
        (self.anexos if anexo else self.secciones).append(seccion)
        self.razones.append(f"{'Anexo' if anexo else 'Sección'} «{seccion}»: {razon}")


def _cargar(base: Path, ruta: str | None):
    return yaml.safe_load((base / ruta).read_text(encoding="utf-8")) if ruta else None


def planificar(manifiesto: dict, base: Path) -> Plan:
    """Reglas explícitas: qué secciones y anexos lleva el informe, y por qué."""
    p = Plan()
    red = manifiesto.get("red")
    if red:
        p.agregar("sistema", "el estudio trae un modelo de red; se describen sus elementos.")
        p.agregar("flujo", "hay modelo de red: se calcula el flujo de cargas y se verifica NTC 1340 / NTC 2050.")
        if manifiesto.get("cortocircuito") or manifiesto.get("fallas"):
            p.agregar("cortocircuito", "se pidieron corrientes de cortocircuito IEC 60909"
                      + (f" (incluye {', '.join(manifiesto.get('fallas') or [])})." if manifiesto.get("fallas") else "."))
    m = _cargar(base, manifiesto.get("malla"))
    if m is not None:
        enlace = "desde_red" in (m.get("falla") or {})
        p.agregar("malla", "hay diseño de malla: memoria de cálculo IEEE 80-2013"
                  + (", con 3I0 tomado de la falla 1F del modelo de red." if enlace else "."))
        if enlace and "cortocircuito" not in p.secciones and red:
            p.agregar("cortocircuito", "la malla usa la falla 1F del modelo: se incluye el cortocircuito para trazabilidad.")
    b = _cargar(base, manifiesto.get("baterias"))
    if b is not None:
        p.agregar("baterias", "hay ciclo de trabajo de servicios auxiliares: memoria IEEE 485-2020"
                  + (" y cargador IEEE 946-2020." if b.get("cargador") else "."))
    if manifiesto.get("subestacion"):
        p.agregar("subestacion", "hay configuración de barras: unifilar y comparación de confiabilidad.")
    if not p.secciones:
        raise ValueError("el manifiesto no trae ningún insumo (red, malla, baterias o subestacion)")
    entradas = [k for k in ("red", "malla", "baterias", "subestacion") if manifiesto.get(k)]
    p.agregar("datos", f"se transcriben los datos de entrada ({', '.join(entradas)}) para que el cálculo sea reproducible.",
              anexo=True)
    p.agregar("normas", "trazabilidad de normas y ecuaciones usadas en las secciones incluidas.", anexo=True)
    return p


# ------------------------------------------------------------------ figuras
def _planta_malla_png(malla, ruta: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from .dxf import posiciones_varillas
    fig, ax = plt.subplots(figsize=(6, 6 * malla.ly / malla.lx))
    for i in range(malla.nx):
        y = i * malla.ly / (malla.nx - 1)
        ax.plot([0, malla.lx], [y, y], color="#e65100", lw=1)
    for j in range(malla.ny):
        x = j * malla.lx / (malla.ny - 1)
        ax.plot([x, x], [0, malla.ly], color="#e65100", lw=1)
    for x, y in posiciones_varillas(malla):
        ax.plot(x, y, "x", color="#b71c1c", ms=7, mew=2)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(ruta, dpi=160)
    plt.close(fig)
    return ruta


def _figura(ruta: Path, pie: str, ancho: str = r"0.85\textwidth") -> str:
    return (r"\begin{figure}[H]\centering\includegraphics[width=" + ancho + "]{" + ruta.name + "}"
            r"\caption{" + esc(pie) + r"}\end{figure}")


# ------------------------------------------------------------------ secciones
def _sec_sistema(red) -> str:
    out = [r"\section{Descripción del sistema}", esc(red.descripcion.strip())]
    out.append(tabla(["Barra", "Tensión nominal [kV]"], [[b.etiqueta, num(b.un_kV, 3)] for b in red.barras],
                     titulo="Barras del sistema"))
    if red.lineas:
        out.append(tabla(["Elemento", "Desde-hasta", "Conductor", "L [m]", "R [Ω/km]", "X [Ω/km]", "Origen"],
                         [[l.etiqueta, f"{l.desde}-{l.hasta}", l.conductor or "-", num(l.longitud_km * 1000, 0),
                           num(l.r_ohm_km, 3), num(l.x_ohm_km, 3), l.origen] for l in red.lineas],
                         "lllrrrl", "Líneas y cables"))
    if red.transformadores:
        out.append(tabla(["Elemento", "S [kVA]", "Tensiones [kV]", "uk [%]", "Grupo", "Origen"],
                         [[t.etiqueta, num(t.sn_MVA * 1000, 0), f"{t.un_at_kV:g}/{t.un_bt_kV:g}", num(t.uk_pct),
                           t.grupo, t.origen] for t in red.transformadores], "lrrrll", "Transformadores"))
    if red.cargas:
        out.append(tabla(["Carga", "Barra", "P [kW]", "Q [kvar]", "Origen"],
                         [[c.etiqueta, c.barra, num(c.p_MW * 1000, 1), num(c.q_Mvar * 1000, 1), c.origen]
                          for c in red.cargas], "llrrl", "Cargas"))
    sup = red.supuestos()
    out.append(r"\subsection{Datos supuestos y deducidos}")
    if sup:
        out.append("Los siguientes datos no provienen de planos, placas ni fichas y deben confirmarse antes de firmar:")
        out.append(r"\begin{itemize}" + "".join(r"\item " + esc(s) for s in sup) + r"\end{itemize}")
    else:
        out.append("Todos los datos del modelo provienen de fuentes documentadas.")
    return "\n\n".join(out)


def _sec_flujo(red, resultados: dict, figs: Path) -> str:
    from .diagrama import dibujar
    from .normas import verificar
    out = [r"\section{Flujo de cargas y verificación normativa}",
           "Método de Newton-Raphson, sistema AC balanceado (pandapower). Límites según los criterios del modelo "
           "(NTC 1340 para tensión, NTC 2050 para caída de tensión y cargabilidad)."]
    for esc_id, res in resultados.items():
        e = red.escenario(esc_id)
        out.append(r"\subsection{Escenario " + esc(esc_id) + " -- " + esc(e.descripcion) + "}")
        out.append(f"Temperatura de conductores {num(e.temperatura_C, 0)} °C; convergió: "
                   f"{'sí' if res.convergio else 'NO'}.")
        png = [f for f in dibujar(red, res, figs / f"unifilar_red_{esc_id}") if f.suffix == ".png"][0]
        out.append(_figura(png, f"Diagrama unifilar con resultados, escenario {esc_id}."))
        out.append(tabla(["Barra", "U [kV]", "u [p.u.]", "Ángulo [°]"],
                         [[b, num(r.ul_kV, 4), num(r.u_pu, 4), num(r.angulo_deg, 2)] for b, r in res.barras.items()],
                         titulo=f"Tensiones, escenario {esc_id}"))
        out.append(tabla(["Rama", "P [kW]", "Q [kvar]", "I [A]", "Carga [%]", "Pérdidas [kW]"],
                         [[rid, num(r.p_MW * 1000), num(r.q_Mvar * 1000), num(r.i_kA * 1000, 1),
                           num(r.cargabilidad_pct, 1), num(r.perdidas_kW, 3)] for rid, r in res.ramas.items()],
                         titulo=f"Flujos por las ramas, escenario {esc_id}"))
        v = verificar(red, res)
        out.append(tabla(["Criterio", "Norma", "Elemento", "Valor", "Límite", "Estado"],
                         [[x.criterio, x.norma, x.elemento, f"{num(x.valor)} {x.unidad}", f"{x.limite} {x.unidad}",
                           Crudo(r"\textcolor{" + {"cumple": "ok", "alerta": "alerta", "no cumple": "mal"}[x.estado]
                                 + "}{" + x.estado.upper() + "}")] for x in v],
                         "lllrrl", f"Verificación normativa, escenario {esc_id}"))
    return "\n\n".join(out)


def _sec_cortocircuito(resultados: dict) -> str:
    out = [r"\section{Corrientes de cortocircuito}",
           "IEC 60909, caso máximo (factor de tensión $c = 1{,}1$), calculado con pandapower. "
           "La norma aplica el factor de corrección $K_T$ a la impedancia de los transformadores de red."]
    nombres = {"1f": "monofásica a tierra", "2f": "bifásica", "2ft": "bifásica a tierra"}
    for esc_id, res in resultados.items():
        if res.cortocircuito:
            out.append(tabla(["Barra", "Ik'' [kA]", "Sk'' [MVA]", "ip [kA]"],
                             [[b, num(c.ikss_kA, 3), num(c.skss_MVA, 2), num(c.ip_kA or 0, 3)]
                              for b, c in res.cortocircuito.items()],
                             titulo=f"Falla trifásica, escenario {esc_id}"))
        for tipo, d in res.fallas.items():
            out.append(tabla(["Barra", "Ik'' [kA]", "ip [kA]"],
                             [[b, num(c.ikss_kA, 3), num(c.ip_kA or 0, 3)] for b, c in d.items()],
                             titulo=f"Falla {nombres.get(tipo, tipo)}, escenario {esc_id}"))
    return "\n\n".join(out)


def _sec_malla(d: dict, base: Path, figs: Path) -> tuple[str, list[str]]:
    from .adaptadores import obtener
    from .modelo import Red
    from .puesta_tierra import Falla, Malla, Suelo, disenar
    f = dict(d["falla"])
    origen_i = "dato del diseño"
    if "desde_red" in f:
        ref = f.pop("desde_red")
        red = Red.cargar(base / ref["red"])
        res = obtener("pandapower").cortocircuito(red, ref.get("escenario"), "1f")
        f["tres_i0"] = res.fallas["1f"][ref["barra"]].ikss_kA * 1000
        origen_i = f"falla 1F en {ref['barra']} del modelo de red (IEC 60909)"
    suelo, malla, falla = Suelo(**d["suelo"]), Malla(**d["malla"]), Falla(**f)
    peso = d.get("peso_kg", 70)
    r = disenar(suelo, malla, falla, peso, d.get("material", "cu_duro"))
    ts = falla.ts or falla.tf
    k = {50: "0{,}116", 70: "0{,}157"}[peso]
    eq_paso, eq_toque = {50: (29, 32), 70: (30, 33)}[peso]
    rho_s = suelo.rho_s or suelo.rho
    png = _planta_malla_png(malla, figs / "planta_malla.png")
    out = [r"\section{Memoria de cálculo: malla de puesta a tierra (IEEE Std 80-2013)}",
           r"\subsection{Datos}",
           tabla(["Parámetro", "Valor"], [
               ["Resistividad del suelo ρ", f"{num(suelo.rho, 1)} Ω·m"],
               ["Capa superficial ρs / hs", f"{num(rho_s, 0)} Ω·m / {num(suelo.h_s, 3)} m"],
               ["Malla", f"{num(malla.lx, 1)} m x {num(malla.ly, 1)} m, {malla.nx} x {malla.ny} conductores"],
               ["Espaciamiento D / profundidad h / diámetro d", f"{num(malla.espaciamiento)} m / {num(malla.h)} m / {num(malla.d * 1000, 1)} mm"],
               ["Varillas", f"{malla.n_varillas} de {num(malla.l_varilla, 1)} m"],
               ["Corriente de falla a tierra 3I0", f"{num(falla.tres_i0, 0)} A ({origen_i})"],
               ["Factor de división Sf / duración tf", f"{num(falla.sf)} / {num(falla.tf)} s"],
               ["Criterio de peso corporal", f"{peso} kg"]], "ll"),
           _figura(png, "Planta de la malla (x: varillas).", r"0.55\textwidth"),
           r"\subsection{Cálculo}",
           r"\begin{align}"
           rf"C_s &= 1-\frac{{0{{,}}09\,(1-\rho/\rho_s)}}{{2h_s+0{{,}}09}} = {nm(r.cs, 4)} \tag{{27}}\\"
           rf"E_{{toque,{peso}}} &= (1000+1{{,}}5\,C_s\,\rho_s)\,\frac{{{k}}}{{\sqrt{{t_s}}}} = {nm(r.e_toque_tol, 1)}\ \text{{V}} \tag{{{eq_toque}}}\\"
           rf"E_{{paso,{peso}}} &= (1000+6\,C_s\,\rho_s)\,\frac{{{k}}}{{\sqrt{{t_s}}}} = {nm(r.e_paso_tol, 1)}\ \text{{V}} \tag{{{eq_paso}}}\\"
           rf"R_g &= \rho\left[\frac{{1}}{{L_T}}+\frac{{1}}{{\sqrt{{20A}}}}\left(1+\frac{{1}}{{1+h\sqrt{{20/A}}}}\right)\right] = {nm(r.rg, 3)}\ \Omega \tag{{57}}\\"
           rf"I_G &= D_f\,S_f\,3I_0 = {nm(r.df, 3)}\cdot{nm(falla.sf)}\cdot{nm(falla.tres_i0, 0)} = {nm(r.ig, 0)}\ \text{{A}} \tag{{68-69}}\\"
           rf"GPR &= I_G\,R_g = {nm(r.gpr, 0)}\ \text{{V}} \notag\\"
           rf"n &= n_a\,n_b\,n_c\,n_d = {nm(r.n, 3)},\quad K_{{ii}} = {nm(r.kii, 3)},\quad K_i = 0{{,}}644+0{{,}}148\,n = {nm(r.ki, 3)} \tag{{94}}\\"
           rf"K_m &= \frac{{1}}{{2\pi}}\left[\ln\!\left(\frac{{D^2}}{{16hd}}+\frac{{(D+2h)^2}}{{8Dd}}-\frac{{h}}{{4d}}\right)+\frac{{K_{{ii}}}}{{K_h}}\ln\frac{{8}}{{\pi(2n-1)}}\right] = {nm(r.km, 4)} \tag{{86}}\\"
           rf"E_m &= \frac{{\rho\,K_m\,K_i\,I_G}}{{L_M}} = {nm(r.em, 1)}\ \text{{V}} \tag{{85}}\\"
           rf"K_s &= \frac{{1}}{{\pi}}\left[\frac{{1}}{{2h}}+\frac{{1}}{{D+h}}+\frac{{1}}{{D}}\left(1-0{{,}}5^{{n-2}}\right)\right] = {nm(r.ks, 4)} \tag{{99}}\\"
           rf"E_s &= \frac{{\rho\,K_s\,K_i\,I_G}}{{0{{,}}75L_C+0{{,}}85L_R}} = {nm(r.es, 1)}\ \text{{V}} \tag{{97}}\\"
           rf"A &= I\,K_f\sqrt{{t_c}} = {nm(r.seccion_min_mm2, 1)}\ \text{{mm}}^2 \tag{{47}}"
           r"\end{align}"
           f"\n\nCon $t_s = {num(ts)}$ s. Los números de ecuación son los de IEEE Std 80-2013.",
           r"\subsection{Verificación}",
           tabla(["Criterio", "Calculado", "Tolerable", "Estado"], [
               ["Tensión de toque (malla)", f"{num(r.em, 1)} V", f"{num(r.e_toque_tol, 1)} V", estado(r.cumple_toque)],
               ["Tensión de paso", f"{num(r.es, 1)} V", f"{num(r.e_paso_tol, 1)} V", estado(r.cumple_paso)]], "lrrl")]
    obs = list(r.notas)
    if not r.cumple:
        out.append(r"\paragraph{Recomendación de rediseño.} El diseño no cumple. IEEE 80 (16.4, paso 11) sugiere reducir "
                   r"el espaciamiento entre conductores, agregar varillas en el perímetro, aumentar la longitud de "
                   r"varillas o reducir la corriente de malla; repita el cálculo con la nueva geometría.")
    return "\n\n".join(out), obs


def _sec_baterias(d: dict) -> tuple[str, list[str]]:
    from .baterias import (Periodo, ah_extraidos, cargador, celda_comercial, dimensionar, numero_celdas,
                           tension_minima_celda)
    s, cel, ale = d["sistema"], d["celda"], d.get("aleatoria")
    n, v_ig = numero_celdas(s["v_max"], s["v_igualacion_celda"])
    ciclo = [Periodo(**p) for p in d["ciclo"]]
    r = dimensionar(ciclo, {float(k): v for k, v in cel["factores"].items()}, cel.get("tipo_factor", "kt"),
                    Periodo(**ale) if ale else None, d.get("temperatura_c", 25.0), d.get("margen", 1.10),
                    d.get("envejecimiento", 1.25))
    elegida = celda_comercial(r.corregido, cel["comerciales"]) if cel.get("comerciales") else None
    fac = "K_t" if cel.get("tipo_factor", "kt") == "kt" else "1/R_t"
    out = [r"\section{Memoria de cálculo: banco de baterías (IEEE Std 485-2020)}",
           r"\subsection{Número de celdas}",
           rf"$N = V_{{max}}/V_{{igualación}} = {nm(s['v_max'], 0)}/{nm(s['v_igualacion_celda'])} \Rightarrow {n}$ celdas "
           rf"(igualación {num(v_ig, 1)} V); tensión mínima por celda $V_{{min}}/N = {nm(tension_minima_celda(s['v_min'], n), 3)}$ V.",
           r"\subsection{Ciclo de trabajo}",
           tabla(["Periodo", "Corriente [A]", "Duración [min]"],
                 [[i + 1, num(p.amperios, 1), num(p.minutos, 0)] for i, p in enumerate(ciclo)]
                 + ([["Aleatoria", num(ale["amperios"], 1), num(ale["minutos"], 0)]] if ale else []), "lrr"),
           r"\subsection{Tamaño de celda}",
           rf"$F_S = \sum_{{P=1}}^{{S}} (A_P - A_{{P-1}})\,{fac}$ (ec. 4 de IEEE 485); se omiten las secciones con $A_{{S+1}} > A_S$.",
           tabla(["Sección", f"F_S [{r.unidad}]"],
                 [[sec, num(fs, 1) + (" (máxima)" if sec == r.seccion_maxima else "")] for sec, fs in r.secciones.items()], "lr"),
           rf"Tamaño sin corregir: ${nm(r.tamano_ciclo, 1)} + {nm(r.tamano_aleatorio, 1)} = {nm(r.sin_corregir, 1)}$ {esc(r.unidad)}. "
           rf"Corregido: ${nm(r.sin_corregir, 1)}\times{nm(r.factor_temperatura)}\times{nm(r.margen)}\times{nm(r.envejecimiento)}"
           rf" = \mathbf{{{nm(r.corregido, 1)}}}$ {esc(r.unidad)} (temperatura, margen y envejecimiento)."
           + (f" Celda comercial elegida: {num(elegida, 0)} {esc(r.unidad)}." if elegida else "")]
    if cg := d.get("cargador"):
        c_ah = elegida if cg.get("ah") == "nominal" and elegida else ah_extraidos(ciclo, Periodo(**ale) if ale else None)
        rc = cargador(c_ah, cg["tiempo_recarga_h"], cg["carga_continua_a"], cg.get("tipo_bateria", "VLA"),
                      cg.get("factores_k"), cg.get("carga_no_continua_a", 0.0), cg.get("comerciales"))
        out += [r"\subsection{Cargador (IEEE Std 946-2020)}",
                r"\begin{align}"
                rf"I_c &= K\left(\frac{{C\,e}}{{t}}+I_L\right) = {nm(rc.k, 3)}\left(\frac{{{nm(c_ah, 1)}\cdot{nm(rc.e)}}}{{{nm(cg['tiempo_recarga_h'], 0)}}}+{nm(cg['carga_continua_a'], 1)}\right) = {nm(rc.ic, 1)}\ \text{{A}} \tag{{1}}\\"
                rf"I_2 &= K\,(I_L+I_{{LN}}) = {nm(rc.i2, 1)}\ \text{{A}},\qquad I_3 = \max(I_c, I_2) = {nm(rc.i3, 1)}\ \text{{A}} \tag{{3}}"
                r"\end{align}"
                + (f"\n\nCargador comercial elegido: {num(rc.comercial, 0)} A." if rc.comercial else "")]
    return "\n\n".join(out), list(r.notas)


def _sec_subestacion(d: dict, figs: Path) -> str:
    from .subestacion import CONFIGURACIONES, Bahia, Subestacion, armar, dibujar, resumen_confiabilidad
    bahias = [Bahia(**b) for b in d["bahias"]]
    t = armar(Subestacion(d["nombre"], d["tension_kV"], d["configuracion"], bahias))
    png = dibujar(t, figs / "unifilar_subestacion.png")[0]
    filas = []
    for conf, nombre in CONFIGURACIONES.items():
        try:
            rr = resumen_confiabilidad(armar(Subestacion(d["nombre"], d["tension_kV"], conf, bahias)))
        except ValueError:
            continue
        marca = " (elegida)" if conf == d["configuracion"].upper() else ""
        filas.append([nombre + marca, rr["interruptores"], rr["seccionadores"],
                      f"{rr['max_perdidos_falla_barra']} de {rr['circuitos']}",
                      f"{rr['max_perdidos_mantenimiento_52']} de {rr['circuitos']}"])
    return "\n\n".join([
        r"\section{Configuración de la subestación}",
        f"Subestación {esc(d['nombre'])}, {num(d['tension_kV'], 1)} kV, configuración "
        f"{esc(CONFIGURACIONES[d['configuracion'].upper()])} con {len(bahias)} bahías.",
        _figura(png, "Diagrama unifilar de la subestación."),
        tabla(["Configuración", "52", "89", "Falla en barra", "Mant. de un 52"], filas,
              "lrrrr", "Comparación de configuraciones para las mismas bahías (circuitos perdidos)"),
        "Falla en barra: circuitos que quedan sin conexión con la protección de barras abriendo todo lo conectado a la "
        "barra fallada (estado normal). Mantenimiento: circuitos que no pueden seguir en servicio sin el interruptor, "
        "aun maniobrando seccionadores."])


def _anexo_datos(manifiesto: dict, base: Path) -> str:
    out = [r"\section{Datos de entrada}"]
    for clave in ("red", "malla", "baterias", "subestacion"):
        if manifiesto.get(clave):
            texto = (base / manifiesto[clave]).read_text(encoding="utf-8")
            out.append(r"\subsection{" + esc(f"{clave}: {manifiesto[clave]}") + "}")
            out.append(r"\begin{lstlisting}" + "\n" + texto.rstrip() + "\n" + r"\end{lstlisting}")
    return "\n\n".join(out)


def _anexo_normas(plan: Plan, observaciones: list[str]) -> str:
    refs = {"flujo": "NTC 1340 (tensión en estado estable); NTC 2050 (caída de tensión y ampacidad).",
            "cortocircuito": "IEC 60909-0 (corrientes de cortocircuito; factor c y corrección K_T).",
            "malla": "IEEE Std 80-2013, cláusulas 8, 11, 14-16 y ecuaciones 27, 29-33, 47, 57, 84-99.",
            "baterias": "IEEE Std 485-2020, cláusula 6 y Tabla 1; IEEE Std 946-2020, 7.3 y Tabla 1.",
            "subestacion": "Configuraciones de barras (syllabus de Subestaciones, sección C)."}
    out = [r"\section{Normas, ecuaciones y observaciones}",
           r"\begin{itemize}" + "".join(r"\item \textbf{" + esc(s) + "}: " + esc(refs[s])
                                        for s in plan.secciones if s in refs) + r"\end{itemize}"]
    if observaciones:
        out.append(r"\subsection{Observaciones del cálculo}")
        out.append(r"\begin{itemize}" + "".join(r"\item " + esc(o) for o in observaciones) + r"\end{itemize}")
    return "\n\n".join(out)


PREAMBULO = r"""\documentclass[11pt,letterpaper]{article}
\usepackage[spanish,es-noshorthands,es-nodecimaldot]{babel}
\usepackage{fontspec}
\usepackage[margin=2.3cm]{geometry}
\usepackage{amsmath,booktabs,longtable,graphicx,float,xcolor,listings,caption}
\usepackage[hidelinks]{hyperref}
\definecolor{ok}{HTML}{2E7D32}\definecolor{alerta}{HTML}{EF6C00}\definecolor{mal}{HTML}{C62828}
\lstset{basicstyle=\ttfamily\footnotesize,breaklines=true,columns=fullflexible,frame=single,
  literate={á}{{\'a}}1 {é}{{\'e}}1 {í}{{\'i}}1 {ó}{{\'o}}1 {ú}{{\'u}}1 {ñ}{{\~n}}1 {Á}{{\'A}}1 {°}{{$^\circ$}}1 {Ω}{{$\Omega$}}1}
\setlength{\parindent}{0pt}\setlength{\parskip}{0.5em}
"""


def generar(manifiesto_ruta: str | Path, carpeta: str | Path, compilar: bool = True) -> dict[str, Path]:
    """Escribe informe.tex (y figuras) en `carpeta`; si hay compilador, también informe.pdf."""
    manifiesto_ruta = Path(manifiesto_ruta)
    base = manifiesto_ruta.parent
    m = yaml.safe_load(manifiesto_ruta.read_text(encoding="utf-8"))
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    plan = planificar(m, base)
    textos = _cargar(base, m.get("textos")) or {}
    cuerpo: list[str] = []
    observaciones: list[str] = []
    resultados: dict = {}
    red = None
    if m.get("red"):
        from .adaptadores import obtener
        from .modelo import Red
        red = Red.cargar(base / m["red"])
        pp = obtener("pandapower")
        ids = [e.id for e in red.escenarios] if m.get("escenarios", "todos") == "todos" else list(m["escenarios"])
        for e in ids:
            res = pp.flujo(red, e)
            if "cortocircuito" in plan.secciones:
                res.cortocircuito = pp.cortocircuito(red, e).cortocircuito
                for tipo in m.get("fallas") or []:
                    res.fallas.update(pp.cortocircuito(red, e, tipo).fallas)
            resultados[e] = res
        observaciones += [f"Supuesto: {s}" for s in red.supuestos()]

    cuerpo.append(r"\section{Alcance}")
    cuerpo.append(esc(textos.get("introduccion") or
                      "Este informe reúne los cálculos del estudio. Las secciones se incluyeron según los insumos "
                      "disponibles, con las siguientes decisiones:"))
    cuerpo.append(r"\begin{itemize}" + "".join(r"\item " + esc(x) for x in plan.razones) + r"\end{itemize}")
    for s in plan.secciones:
        if s == "sistema":
            cuerpo.append(_sec_sistema(red))
        elif s == "flujo":
            cuerpo.append(_sec_flujo(red, resultados, carpeta))
        elif s == "cortocircuito":
            cuerpo.append(_sec_cortocircuito(resultados))
        elif s == "malla":
            t, o = _sec_malla(_cargar(base, m["malla"]), base, carpeta)
            cuerpo.append(t)
            observaciones += [f"Malla: {x}" for x in o]
        elif s == "baterias":
            t, o = _sec_baterias(_cargar(base, m["baterias"]))
            cuerpo.append(t)
            observaciones += [f"Baterías: {x}" for x in o]
        elif s == "subestacion":
            cuerpo.append(_sec_subestacion(_cargar(base, m["subestacion"]), carpeta))
    if textos.get("analisis") or textos.get("conclusiones"):
        cuerpo.append(r"\section{Análisis y conclusiones}")
        for par in (textos.get("analisis") or "").split("\n\n"):
            if par.strip():
                cuerpo.append(esc(par.strip()))
        if textos.get("conclusiones"):
            items = [x.strip().lstrip("-• ") for x in textos["conclusiones"].split("\n") if x.strip()]
            cuerpo.append(r"\begin{enumerate}" + "".join(r"\item " + esc(x) for x in items) + r"\end{enumerate}")
    cuerpo.append(r"\appendix")
    for a in plan.anexos:
        cuerpo.append(_anexo_datos(m, base) if a == "datos" else _anexo_normas(plan, observaciones))

    titulo = m.get("titulo", "Informe técnico")
    tex = (PREAMBULO + r"\title{" + esc(titulo) + r"}\author{" + esc(m.get("autor", "")) + r"}\date{"
           + dt.date.today().isoformat() + "}\n" + r"\begin{document}\maketitle" + "\n"
           r"\begin{center}\small\textit{Borrador generado por power-studies. Debe ser revisado y firmado por un "
           r"ingeniero electricista con matrícula profesional vigente.}\end{center}" + "\n"
           r"\tableofcontents\newpage" + "\n\n" + "\n\n".join(cuerpo) + "\n\n" + r"\end{document}" + "\n")
    ruta_tex = carpeta / "informe.tex"
    ruta_tex.write_text(tex, encoding="utf-8")
    salida = {"tex": ruta_tex}
    if compilar:
        pdf = compilar_pdf(ruta_tex)
        if pdf:
            salida["pdf"] = pdf
    return salida


def compilador() -> str | None:
    for nombre in ("tectonic", str(Path.home() / ".local/bin/tectonic"), "latexmk", "xelatex"):
        if shutil.which(nombre) or Path(nombre).exists():
            return shutil.which(nombre) or nombre
    return None


def compilar_pdf(ruta_tex: Path) -> Path | None:
    """Compila con Tectonic (o latexmk/xelatex). Devuelve None si no hay compilador."""
    c = compilador()
    if c is None:
        return None
    if "tectonic" in Path(c).name:
        cmd = [c, "-X", "compile", ruta_tex.name]
    elif "latexmk" in Path(c).name:
        cmd = [c, "-xelatex", "-interaction=nonstopmode", ruta_tex.name]
    else:
        cmd = [c, "-interaction=nonstopmode", ruta_tex.name]
    proc = subprocess.run(cmd, cwd=ruta_tex.parent, capture_output=True, text=True, timeout=900)
    pdf = ruta_tex.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"LaTeX no compiló ({Path(c).name}):\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    if "tectonic" not in Path(c).name and "latexmk" not in Path(c).name:  # segunda pasada para el índice
        subprocess.run(cmd, cwd=ruta_tex.parent, capture_output=True, text=True, timeout=900)
    return pdf
