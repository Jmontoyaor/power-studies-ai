# -*- coding: utf-8 -*-
"""
pf_construir_red.py  -  Modelo neutro -> DIgSILENT PowerFactory (paso 2)

Lee un modelo neutro (JSON generado con `power-studies exportar --herramienta
powerfactory`) y, dentro del proyecto ACTIVO de PowerFactory:
  1. crea una red nueva (ElmNet) con barras, cables/líneas, transformadores,
     cargas, generación FV y red externa, con sus tipos en la librería;
  2. dibuja el diagrama unifilar (ver ESTRATEGIA GRÁFICA abajo);
  3. corre flujo de cargas (y cortocircuito IEC 60909 si se pide);
  4. guarda los resultados en el formato común (Resultados JSON) para que
     los agentes los comparen con pandapower/OpenDSS y redacten el informe.

Solo usa la biblioteca estándar: funciona con el Python que trae PowerFactory.

USO A — dentro de PowerFactory: cree un ComPython que apunte a este archivo,
         ajuste MODELO_JSON y ejecútelo con el proyecto destino activo.
USO B — desde fuera (modo motor): ver herramientas/powerfactory/pf_motor.py.

ESTRATEGIA GRÁFICA (en orden):
  a) Herramienta de diagramado automático de PowerFactory (2021+), si existe
     en su versión: genera el unifilar a partir de la topología.
  b) Si no, crea los símbolos uno a uno en las posiciones del modelo neutro
     (las calcula power_studies.diagrama). Los nombres de símbolos se toman
     de SIMBOLOS; si su versión usa otros, corra pf_exportar_modelo.py sobre
     un diagrama suyo y copie los valores de "simbolo".
  c) Si ambos fallan, la red queda creada y simulada; en la GUI use
     "Dibujar elementos de red existentes" para dibujarla.

ESTADO: escrito contra la API documentada de PowerFactory, aún NO probado en
una instalación real. Reporte los errores de la ventana de salida.
"""
import json
import math
import os

MODELO_JSON = os.path.join(os.path.expanduser("~"), "Documents", "power_studies", "modelo.json")
RESULTADOS_JSON = os.path.join(os.path.dirname(MODELO_JSON), "resultados_powerfactory.json")
ESCENARIO = None            # None = el primero del modelo
NOMBRE_RED = None           # None = "PS_" + proyecto
CORTOCIRCUITO = True
DIBUJAR = True
ESCALA_GRAFICO = 1.0        # posiciones del modelo (mm) -> coordenadas del diagrama

SIMBOLOS = {                # clase -> nombre de símbolo (ajustable por versión)
    "ElmTerm": "TermStrip",
    "ElmXnet": "d_net",
    "ElmLne": "d_lin",
    "ElmTr2": "d_tr2",
    "ElmLod": "d_load",
    "ElmGenstat": "d_genstat",
}

try:
    import powerfactory
except ImportError:            # permite importar el módulo en pruebas
    powerfactory = None


def partir_grupo(grupo):
    """'Dyn5' -> ('D', 'YN', '5');  'YNd11' -> ('YN', 'D', '11')."""
    g = grupo.strip().upper()
    digitos = "".join(c for c in g if c.isdigit()) or "0"
    letras = g[: len(g) - len(digitos)]
    for hv in ("YN", "ZN", "D", "Y", "Z"):
        if letras.startswith(hv):
            return hv, letras[len(hv):] or "Y", digitos
    return "D", "YN", digitos


class Constructor:
    def __init__(self, app, modelo, escenario=None):
        self.app = app
        self.m = modelo
        self.esc = self._escenario(escenario)
        self.obj = {}            # id neutro -> objeto PF
        self.log = []

    # ------------------------------------------------------------ util
    def p(self, msg):
        self.log.append(msg)
        try:
            self.app.PrintPlain(msg)
        except Exception:
            print(msg)

    def _escenario(self, id_):
        escs = self.m.get("escenarios") or [{"id": "base"}]
        if id_ is None:
            return escs[0]
        for e in escs:
            if e["id"] == id_:
                return e
        raise KeyError(id_)

    def _barra(self, id_):
        for b in self.m["barras"]:
            if b["id"] == id_:
                return b
        raise KeyError(id_)

    @staticmethod
    def _r_temp(l, t):
        t0 = 234.5 if l.get("material", "cu") == "cu" else 228.1
        return l["r_ohm_km"] * (t0 + t) / (t0 + l.get("temperatura_ref_C", 20.0))

    def _crear(self, padre, clase, nombre):
        """Crea o reutiliza un objeto (idempotente)."""
        existentes = padre.GetContents(nombre + "." + clase)
        if existentes:
            return existentes[0]
        o = padre.CreateObject(clase, nombre)
        if o is None:
            raise RuntimeError("no se pudo crear %s.%s" % (nombre, clase))
        return o

    def _cubiculo(self, barra_id, sufijo):
        term = self.obj[barra_id]
        return self._crear(term, "StaCubic", "Cub_" + sufijo)

    # ------------------------------------------------------------ red
    def construir(self):
        app = self.app
        proyecto = app.GetActiveProject()
        if proyecto is None:
            raise RuntimeError("Active un proyecto antes de correr el script")
        carpeta_redes = app.GetProjectFolder("netdat")
        self.lib = self._crear(app.GetProjectFolder("equip"), "IntFolder", "power_studies")
        nombre = NOMBRE_RED or ("PS_" + self.m["proyecto"])[:40]
        self.red = self._crear(carpeta_redes, "ElmNet", nombre)
        self.red.frnom = self.m.get("frecuencia_Hz", 60)
        temp = self.esc.get("temperatura_C", 20.0)
        escala = self.esc.get("escala_carga", 1.0)
        taps = self.esc.get("taps", {})

        for b in self.m["barras"]:
            t = self._crear(self.red, "ElmTerm", b["id"])
            t.uknom = b["un_kV"]
            t.iUsage = 0                     # barraje
            if b.get("nombre"):
                t.desc = [b["nombre"]]
            self.obj[b["id"]] = t

        for x in self.m["redes_externas"]:
            o = self._crear(self.red, "ElmXnet", x["id"])
            o.bus1 = self._cubiculo(x["barra"], x["id"])
            o.bustp = "SL"
            o.usetp = x.get("u_pu", 1.0)
            o.phiini = x.get("angulo_deg", 0.0)
            o.snss = x.get("scc_max_MVA", 100.0)
            o.rntxn = x.get("r_x_max", 0.1)
            o.snssmin = x.get("scc_min_MVA") or 0.8 * o.snss
            o.rntxnmin = x.get("r_x_min") if x.get("r_x_min") is not None else o.rntxn
            self.obj[x["id"]] = o

        for l in self.m.get("lineas", []):
            typ = self._crear(self.lib, "TypLne", "T_" + l["id"])
            typ.uline = self._barra(l["desde"])["un_kV"]
            typ.sline = l["in_kA"]
            # la resistencia se carga ya corregida a la temperatura del escenario
            typ.rline = self._r_temp(l, temp)
            typ.xline = l["x_ohm_km"]
            typ.bline = 2 * math.pi * self.m.get("frecuencia_Hz", 60) * l.get("c_nF_km", 0.0) * 1e-3  # uS/km
            typ.rline0 = l.get("r0_ohm_km") or 3 * typ.rline
            typ.xline0 = l.get("x0_ohm_km") or 3 * typ.xline
            typ.cohl_ = 0 if l.get("tipo", "cable") == "cable" else 1
            typ.nlnph = 3
            o = self._crear(self.red, "ElmLne", l["id"])
            o.typ_id = typ
            o.dline = l["longitud_km"]
            o.nlnum = l.get("paralelos", 1)
            o.bus1 = self._cubiculo(l["desde"], l["id"])
            o.bus2 = self._cubiculo(l["hasta"], l["id"])
            self.obj[l["id"]] = o

        for t in self.m.get("transformadores", []):
            typ = self._crear(self.lib, "TypTr2", "T_" + t["id"])
            typ.strn = t["sn_MVA"]
            typ.utrn_h = t["un_at_kV"]
            typ.utrn_l = t["un_bt_kV"]
            typ.uktr = t["uk_pct"]
            typ.pcutr = t["pcu_kW"]
            typ.pfe = t.get("p0_kW", 0.0)
            typ.curmg = t.get("i0_pct", 0.0)
            typ.uk0tr = t["uk_pct"]
            hv, lv, digitos = partir_grupo(t.get("grupo", "Dyn5"))
            typ.tr2cn_h = hv
            typ.tr2cn_l = lv
            typ.nt2ag = int(digitos)
            typ.tap_side = 0 if t.get("tap_lado", "at") == "at" else 1
            typ.dutap = t.get("tap_paso_pct", 2.5)
            typ.ntpmn = t.get("tap_min", -2)
            typ.ntpmx = t.get("tap_max", 2)
            typ.nntap0 = 0
            o = self._crear(self.red, "ElmTr2", t["id"])
            o.typ_id = typ
            o.bushv = self._cubiculo(t["barra_at"], t["id"])
            o.buslv = self._cubiculo(t["barra_bt"], t["id"])
            o.nntap = taps.get(t["id"], t.get("tap_pos", 0))
            self.obj[t["id"]] = o

        for c in self.m.get("cargas", []):
            o = self._crear(self.red, "ElmLod", c["id"])
            o.bus1 = self._cubiculo(c["barra"], c["id"])
            o.mode_inp = "PQ"
            o.plini = c["p_MW"] * escala
            o.qlini = c.get("q_Mvar", 0.0) * escala
            self.obj[c["id"]] = o

        for g in self.m.get("generadores_pv", []):
            o = self._crear(self.red, "ElmGenstat", g["id"])
            o.bus1 = self._cubiculo(g["barra"], g["id"])
            o.sgn = g["sn_MVA"]
            o.pgini = g["p_MW"]
            o.qgini = g.get("q_Mvar", 0.0)
            o.av_mode = "constq"
            o.aCategory = "pv"
            self.obj[g["id"]] = o

        self.p("Red '%s' creada: %d elementos" % (self.red.loc_name, len(self.obj)))
        self._activar_red()

    def _activar_red(self):
        try:
            self.red.Activate()
        except Exception:
            pass

    # ------------------------------------------------------------ gráfico
    def dibujar(self):
        if self._dibujo_automatico():
            return "automatico"
        if self._dibujo_manual():
            return "manual"
        self.p("AVISO: no se pudo dibujar el unifilar automáticamente. Use en la GUI "
               "'Dibujar elementos de red existentes' sobre la red " + self.red.loc_name)
        return "pendiente"

    def _dibujo_automatico(self):
        try:
            cmd = self.app.GetFromStudyCase("ComSgllayout")
            if cmd is None:
                return False
            for attr, val in (("iAction", 0), ("pGrid", self.red)):
                try:
                    setattr(cmd, attr, val)
                except Exception:
                    pass
            ok = cmd.Execute() == 0
            if ok:
                self.p("Unifilar generado con la herramienta de diagramado automático")
            return ok
        except Exception as e:
            self.p("Diagramado automático no disponible: %s" % e)
            return False

    def _dibujo_manual(self):
        try:
            carpeta = self.app.GetProjectFolder("dia")
            dia = self._crear(carpeta, "IntGrfnet", self.red.loc_name)
            dia.pDataFolder = self.red
            dia.snap_on = 1
            clases = {"barras": "ElmTerm", "redes_externas": "ElmXnet", "lineas": "ElmLne",
                      "transformadores": "ElmTr2", "cargas": "ElmLod", "generadores_pv": "ElmGenstat"}
            pos = {b["id"]: b.get("pos") for b in self.m["barras"]}
            n = 0
            for grupo, clase in clases.items():
                for e in self.m.get(grupo, []):
                    xy = self._posicion(e, grupo, pos)
                    if xy is None:
                        continue
                    g = self._crear(dia, "IntGrf", "G_" + e["id"])
                    g.pDataObj = self.obj[e["id"]]
                    g.sSymNam = SIMBOLOS[clase]
                    g.rCenterX = xy[0] * ESCALA_GRAFICO
                    g.rCenterY = xy[1] * ESCALA_GRAFICO
                    if clase == "ElmTerm":
                        g.rSizeX = 40
                    n += 1
            self.p("Unifilar '%s' creado con %d símbolos (posiciones del modelo neutro)." % (dia.loc_name, n))
            self.p("Revise las conexiones; si faltan, use 'Reconectar' o 'Dibujar elementos existentes'.")
            return n > 0
        except Exception as e:
            self.p("Dibujo manual falló: %s" % e)
            return False

    @staticmethod
    def _posicion(e, grupo, pos):
        def xy(b):
            p = pos.get(b)
            return (p["x"], p["y"]) if p else None
        if grupo == "barras":
            return xy(e["id"])
        if grupo in ("lineas", "transformadores"):
            a = xy(e.get("desde") or e.get("barra_at"))
            b = xy(e.get("hasta") or e.get("barra_bt"))
            return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) if a and b else None
        p = xy(e["barra"])
        if p is None:
            return None
        dy = 25 if grupo == "redes_externas" else -25
        return (p[0], p[1] + dy)

    # ------------------------------------------------------------ cálculo
    def flujo(self):
        ldf = self.app.GetFromStudyCase("ComLdf")
        ldf.iopt_net = 0          # AC balanceado
        ldf.iopt_at = 0           # sin ajuste automático de taps
        err = ldf.Execute()
        res = {"herramienta": "powerfactory", "escenario": self.esc["id"],
               "convergio": err == 0, "barras": {}, "ramas": {}, "cortocircuito": {}, "notas": []}
        if err:
            res["notas"].append("ComLdf devolvió error %s" % err)
            return res
        for b in self.m["barras"]:
            t = self.obj[b["id"]]
            res["barras"][b["id"]] = {"u_pu": t.GetAttribute("m:u"), "ul_kV": t.GetAttribute("m:Ul"),
                                      "angulo_deg": t.GetAttribute("m:phiu")}
        perd = 0.0
        for grupo, lado1, lado2 in (("lineas", "bus1", "bus2"), ("transformadores", "bushv", "buslv")):
            for e in self.m.get(grupo, []):
                o = self.obj[e["id"]]
                pl = o.GetAttribute("c:Ploss") if o.HasAttribute("c:Ploss") else 0.0
                perd += pl
                res["ramas"][e["id"]] = {
                    "p_MW": o.GetAttribute("m:P:" + lado1), "q_Mvar": o.GetAttribute("m:Q:" + lado1),
                    "i_kA": o.GetAttribute("m:I:" + lado1), "i_kA_receptor": o.GetAttribute("m:I:" + lado2),
                    "cargabilidad_pct": o.GetAttribute("c:loading"), "perdidas_kW": pl * 1000}
        res["perdidas_totales_kW"] = perd * 1000
        return res

    def cortocircuito(self, res):
        try:
            shc = self.app.GetFromStudyCase("ComShc")
            shc.iopt_mde = 1         # IEC 60909
            shc.iopt_shc = "3psc"
            shc.iopt_cur = 0         # máximo
            shc.iopt_allbus = 1      # todas las barras
            if shc.Execute():
                res["notas"].append("cortocircuito no se pudo ejecutar")
                return
            for b in self.m["barras"]:
                t = self.obj[b["id"]]
                res["cortocircuito"][b["id"]] = {"ikss_kA": t.GetAttribute("m:Ikss"),
                                                 "skss_MVA": t.GetAttribute("m:Skss"),
                                                 "ip_kA": t.GetAttribute("m:ip")}
            res["notas"].append("Cortocircuito IEC 60909 (máx., trifásico) en PowerFactory")
        except Exception as e:
            res["notas"].append("cortocircuito falló: %s" % e)


def main(app=None, ruta_modelo=MODELO_JSON, ruta_res=RESULTADOS_JSON):
    app = app or powerfactory.GetApplication()
    try:
        app.ClearOutputWindow()
    except Exception:
        pass
    with open(ruta_modelo, encoding="utf-8") as f:
        modelo = json.load(f)
    c = Constructor(app, modelo, ESCENARIO)
    c.construir()
    if DIBUJAR:
        c.dibujar()
    res = c.flujo()
    if CORTOCIRCUITO and res["convergio"]:
        c.cortocircuito(res)
    with open(ruta_res, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    c.p("Resultados guardados en " + ruta_res)
    return res


if __name__ == "__main__":
    main()
