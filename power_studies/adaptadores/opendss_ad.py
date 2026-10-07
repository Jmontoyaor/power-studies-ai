"""Adaptador OpenDSS (EPRI, gratuito). Escribe un script .dss legible y,
si está instalado `opendssdirect.py`, lo resuelve y devuelve resultados.

Nota: OpenDSS modela el grupo delta-estrella con el desfase ANSI (30°), no
el índice horario IEC. Las magnitudes coinciden; los ángulos en BT pueden
diferir del resto de herramientas en un múltiplo de 30°.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..modelo import Red
from ..resultados import ResBarra, ResRama, Resultados
from .base import Adaptador


def _n(s: str) -> str:
    return s.lower().replace(" ", "_")


class OpenDSSAdaptador(Adaptador):
    nombre = "opendss"
    capacidades = ("flujo", "exportar")

    def disponible(self):
        try:
            import opendssdirect  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "pip install opendssdirect.py"

    # ------------------------------------------------------------------
    def script(self, red: Red, escenario: str | None = None) -> str:
        esc = red.escenario(escenario)
        x = red.redes_externas[0]
        kv_slack = red.barra(x.barra).un_kV
        xr = 1.0 / x.r_x_max if x.r_x_max else 10.0
        L = [f"! Generado por power-studies-ai | proyecto: {red.proyecto} | escenario: {esc.id}",
             "clear",
             f"new circuit.{_n(red.proyecto)[:30]} basekv={kv_slack} pu={x.u_pu} angle={x.angulo_deg} "
             f"phases=3 bus1={_n(x.barra)} MVAsc3={x.scc_max_MVA} MVAsc1={x.scc_max_MVA} "
             f"x1r1={xr:.4f} x0r0={xr:.4f} basefreq={red.frecuencia_Hz}",
             f"set defaultbasefrequency={red.frecuencia_Hz}"]
        for l in red.lineas:
            r1 = l.r_a(esc.temperatura_C) / l.paralelos
            x1 = l.x_ohm_km / l.paralelos
            r0 = (l.r0_ohm_km or 3 * l.r_ohm_km) / l.paralelos
            x0 = (l.x0_ohm_km or 3 * l.x_ohm_km) / l.paralelos
            L.append(f"new line.{_n(l.id)} bus1={_n(l.desde)} bus2={_n(l.hasta)} phases=3 "
                     f"length={l.longitud_km} units=km r1={r1:.6f} x1={x1:.6f} r0={r0:.6f} "
                     f"x0={x0:.6f} c1={l.c_nF_km * l.paralelos} c0={l.c_nF_km * l.paralelos} "
                     f"normamps={l.in_kA * 1000 * l.paralelos} emergamps={l.in_kA * 1500 * l.paralelos}")
        for t in red.transformadores:
            tap = esc.taps.get(t.id, t.tap_pos)
            ratio = 1 + tap * t.tap_paso_pct / 100
            taps = f"[{ratio:.4f} 1]" if t.tap_lado == "at" else f"[1 {ratio:.4f}]"
            g = t.grupo.upper()
            c_at = "delta" if g.startswith("D") else "wye"
            c_bt = "delta" if (len(g) > 1 and g[1:].lstrip("N")[:1] == "D") else "wye"
            ukx = math.sqrt(max(t.uk_pct ** 2 - t.ukr_pct ** 2, 1e-9))
            kva = t.sn_MVA * 1000
            imag = t.i0_pct
            nll = t.p0_kW / kva * 100 if kva else 0
            L.append(f"new transformer.{_n(t.id)} phases=3 windings=2 "
                     f"buses=[{_n(t.barra_at)} {_n(t.barra_bt)}] conns=[{c_at} {c_bt}] "
                     f"kvs=[{t.un_at_kV} {t.un_bt_kV}] kvas=[{kva} {kva}] "
                     f"%rs=[{t.ukr_pct / 2:.5f} {t.ukr_pct / 2:.5f}] xhl={ukx:.5f} "
                     f"%noloadloss={nll:.5f} %imag={imag} taps={taps}")
        for c in red.cargas:
            kv = red.barra(c.barra).un_kV
            L.append(f"new load.{_n(c.id)} bus1={_n(c.barra)} phases=3 conn=wye kv={kv} "
                     f"kw={c.p_MW * 1000 * esc.escala_carga:.4f} "
                     f"kvar={c.q_Mvar * 1000 * esc.escala_carga:.4f} model=1 vminpu=0.7 vmaxpu=1.3")
        for g in red.generadores_pv:
            kv = red.barra(g.barra).un_kV
            L.append(f"new generator.{_n(g.id)} bus1={_n(g.barra)} phases=3 kv={kv} "
                     f"kw={g.p_MW * 1000} kvar={g.q_Mvar * 1000} model=1 kva={g.sn_MVA * 1000}")
        bases = sorted({b.un_kV for b in red.barras}, reverse=True)
        L += [f"set voltagebases=[{' '.join(str(b) for b in bases)}]",
              "calcvoltagebases",
              "set mode=snapshot maxiterations=50 tolerance=0.000001",
              "solve"]
        return "\n".join(L) + "\n"

    # ------------------------------------------------------------------
    def flujo(self, red: Red, escenario: str | None = None) -> Resultados:
        import opendssdirect as dss

        esc = red.escenario(escenario)
        res = Resultados(herramienta=self.nombre, escenario=esc.id, convergio=False)
        for linea in self.script(red, esc.id).splitlines():
            if linea and not linea.startswith("!"):
                dss.Text.Command(linea)
        res.convergio = bool(dss.Solution.Converged())
        res.iteraciones = int(dss.Solution.Iterations())
        if not res.convergio:
            return res

        for b in red.barras:
            dss.Circuit.SetActiveBus(_n(b.id))
            va = dss.Bus.puVmagAngle()
            mags = va[0::2][:3]
            angs = va[1::2][:3]
            u = sum(mags) / len(mags)
            res.barras[b.id] = ResBarra(u_pu=u, ul_kV=u * b.un_kV, angulo_deg=angs[0])

        def rama(clase, id_, nominal_A, kv):
            dss.Circuit.SetActiveElement(f"{clase}.{_n(id_)}")
            corr = dss.CktElement.CurrentsMagAng()
            n = dss.CktElement.NumConductors()
            i1 = corr[0]                       # terminal 1, fase A
            i2 = corr[2 * n]                   # terminal 2, fase A
            pw = dss.CktElement.Powers()
            p = sum(pw[0:2 * 3:2]); q = sum(pw[1:2 * 3:2])
            perd = dss.CktElement.Losses()[0] / 1000
            return ResRama(p_MW=p / 1000, q_Mvar=q / 1000, i_kA=i1 / 1000, i_kA_receptor=i2 / 1000,
                           cargabilidad_pct=max(i1, i2 * kv[1] / kv[0]) / nominal_A * 100 if kv else
                           max(i1, i2) / nominal_A * 100,
                           perdidas_kW=perd)

        for l in red.lineas:
            res.ramas[l.id] = rama("line", l.id, l.in_kA * 1000 * l.paralelos, None)
        for t in red.transformadores:
            in_at = t.sn_MVA * 1000 / (math.sqrt(3) * t.un_at_kV)
            res.ramas[t.id] = rama("transformer", t.id, in_at, (t.un_at_kV, t.un_bt_kV))
        res.perdidas_totales_kW = dss.Circuit.Losses()[0] / 1000
        res.notas.append("Ángulos de BT con convención ANSI (delta-estrella = 30°)")
        return res

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None) -> list[Path]:
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"red_{red.escenario(escenario).id}.dss"
        ruta.write_text(self.script(red, escenario), encoding="utf-8")
        return [ruta]
