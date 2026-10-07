"""Adaptador pandapower: 100 % Python y gratuito. Es la referencia local que
corre en cualquier equipo y contra la cual se validan las demás herramientas."""
from __future__ import annotations

import math
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="pandapower")
from pathlib import Path

from ..modelo import Red
from ..resultados import ResBarra, ResCortocircuito, ResRama, Resultados
from .base import Adaptador


def _vector_group(grupo: str) -> str:
    g = grupo.strip()
    letras = "".join(c for c in g if not c.isdigit())
    mapa = {"Dyn": "Dyn", "Dy": "Dyn", "YNd": "YNd", "Yd": "Yd", "Yy": "Yy",
            "YNyn": "YNyn", "Yyn": "Yyn", "Dd": "Dd", "Yzn": "Yzn"}
    return mapa.get(letras, "Dyn")


class PandapowerAdaptador(Adaptador):
    nombre = "pandapower"
    capacidades = ("flujo", "cortocircuito", "exportar")

    def disponible(self):
        try:
            import pandapower  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "pip install pandapower"

    # ------------------------------------------------------------------
    def construir(self, red: Red, escenario: str | None = None):
        import pandapower as pp

        esc = red.escenario(escenario)
        net = pp.create_empty_network(name=red.proyecto, f_hz=red.frecuencia_Hz)
        idx = {}
        for b in red.barras:
            idx[b.id] = pp.create_bus(net, vn_kv=b.un_kV, name=b.id)

        for x in red.redes_externas:
            pp.create_ext_grid(
                net, idx[x.barra], vm_pu=x.u_pu, va_degree=x.angulo_deg, name=x.id,
                s_sc_max_mva=x.scc_max_MVA, rx_max=x.r_x_max,
                s_sc_min_mva=x.scc_min_MVA or x.scc_max_MVA * 0.8,
                rx_min=x.r_x_min if x.r_x_min is not None else x.r_x_max)

        for l in red.lineas:
            pp.create_line_from_parameters(
                net, idx[l.desde], idx[l.hasta], length_km=l.longitud_km,
                r_ohm_per_km=l.r_a(esc.temperatura_C), x_ohm_per_km=l.x_ohm_km,
                c_nf_per_km=l.c_nF_km, max_i_ka=l.in_kA, parallel=l.paralelos,
                name=l.id, endtemp_degree=max(esc.temperatura_C, 80.0))

        for t in red.transformadores:
            tap_pos = esc.taps.get(t.id, t.tap_pos)
            pp.create_transformer_from_parameters(
                net, idx[t.barra_at], idx[t.barra_bt], sn_mva=t.sn_MVA,
                vn_hv_kv=t.un_at_kV, vn_lv_kv=t.un_bt_kV,
                vk_percent=t.uk_pct, vkr_percent=t.ukr_pct,
                pfe_kw=t.p0_kW, i0_percent=t.i0_pct,
                shift_degree=t.desfase_deg, vector_group=_vector_group(t.grupo),
                tap_side="hv" if t.tap_lado == "at" else "lv", tap_neutral=0,
                tap_min=t.tap_min, tap_max=t.tap_max, tap_step_percent=t.tap_paso_pct,
                tap_pos=tap_pos, tap_changer_type="Ratio", name=t.id,
                vk0_percent=t.uk_pct, vkr0_percent=t.ukr_pct, mag0_percent=100,
                mag0_rx=0, si0_hv_partial=0.9)

        for c in red.cargas:
            pp.create_load(net, idx[c.barra], p_mw=c.p_MW * esc.escala_carga,
                           q_mvar=c.q_Mvar * esc.escala_carga, name=c.id)
        for g in red.generadores_pv:
            pp.create_sgen(net, idx[g.barra], p_mw=g.p_MW, q_mvar=g.q_Mvar,
                           sn_mva=g.sn_MVA, k=g.k_cc, name=g.id, type="PV")
        return net

    # ------------------------------------------------------------------
    def flujo(self, red: Red, escenario: str | None = None) -> Resultados:
        import pandapower as pp

        esc = red.escenario(escenario)
        net = self.construir(red, esc.id)
        res = Resultados(herramienta=self.nombre, escenario=esc.id, convergio=False)
        try:
            pp.runpp(net, algorithm="nr", calculate_voltage_angles=True,
                     init="dc", tolerance_mva=1e-9, numba=False, max_iteration=30)
        except Exception as e:  # pandapower lanza LoadflowNotConverged
            res.notas.append(f"no convergió: {e}")
            return res
        res.convergio = True
        res.iteraciones = int(net._ppc["iterations"]) if "iterations" in net._ppc else None

        for i, b in net.bus.iterrows():
            r = net.res_bus.loc[i]
            res.barras[b["name"]] = ResBarra(u_pu=float(r.vm_pu), ul_kV=float(r.vm_pu * b.vn_kv),
                                             angulo_deg=float(r.va_degree))
        for i, l in net.line.iterrows():
            r = net.res_line.loc[i]
            res.ramas[l["name"]] = ResRama(
                p_MW=float(r.p_from_mw), q_Mvar=float(r.q_from_mvar), i_kA=float(r.i_from_ka),
                i_kA_receptor=float(r.i_to_ka), cargabilidad_pct=float(r.loading_percent),
                perdidas_kW=float(r.pl_mw * 1000))
        for i, t in net.trafo.iterrows():
            r = net.res_trafo.loc[i]
            res.ramas[t["name"]] = ResRama(
                p_MW=float(r.p_hv_mw), q_Mvar=float(r.q_hv_mvar), i_kA=float(r.i_hv_ka),
                i_kA_receptor=float(r.i_lv_ka), cargabilidad_pct=float(r.loading_percent),
                perdidas_kW=float(r.pl_mw * 1000))
        res.perdidas_totales_kW = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()) * 1000
        return res

    # ------------------------------------------------------------------
    def cortocircuito(self, red: Red, escenario: str | None = None) -> Resultados:
        """Cortocircuito trifásico IEC 60909 (máximo) en todas las barras."""
        import pandapower.shortcircuit as sc

        esc = red.escenario(escenario)
        net = self.construir(red, esc.id)
        res = Resultados(herramienta=self.nombre, escenario=esc.id, convergio=True)
        sc.calc_sc(net, case="max", fault="3ph", ip=True)  # IEC 60909
        for i, b in net.bus.iterrows():
            r = net.res_bus_sc.loc[i]
            ikss = float(r.ikss_ka)
            res.cortocircuito[b["name"]] = ResCortocircuito(
                ikss_kA=ikss, skss_MVA=math.sqrt(3) * b.vn_kv * ikss,
                ip_kA=float(r.ip_ka) if "ip_ka" in r else None)
        res.notas.append("IEC 60909, caso máximo, falla trifásica")
        return res

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None) -> list[Path]:
        import pandapower as pp

        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / "red_pandapower.json"
        pp.to_json(self.construir(red, escenario), str(ruta))
        return [ruta]
