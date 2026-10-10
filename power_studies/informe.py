"""Informe técnico en Word (.docx).

El esqueleto (tablas, figuras, verificación) se arma de forma determinista
con los resultados; los textos de análisis los puede aportar el agente
redactor mediante `textos` (claves: introduccion, analisis, conclusiones).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from .diagrama import dibujar
from .modelo import Red
from .normas import Verificacion, resumen, verificar
from .resultados import Resultados, comparar

COLORES = {"cumple": "C8E6C9", "alerta": "FFE0B2", "no cumple": "FFCDD2"}


def _sombrear(celda, hex_color):
    tcPr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _tabla(doc, encabezados, filas, estados=None):
    t = doc.add_table(rows=1, cols=len(encabezados))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(encabezados):
        t.rows[0].cells[i].text = h
        t.rows[0].cells[i].paragraphs[0].runs[0].bold = True
    for k, fila in enumerate(filas):
        celdas = t.add_row().cells
        for i, v in enumerate(fila):
            celdas[i].text = str(v)
        if estados and estados[k] in COLORES:
            _sombrear(celdas[-1], COLORES[estados[k]])
    for fila in t.rows:
        for c in fila.cells:
            for p in c.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
    doc.add_paragraph()
    return t


def _f(x, n=2):
    return f"{x:,.{n}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def conclusiones_automaticas(red: Red, res: Resultados, verifs: list[Verificacion]) -> list[str]:
    out = []
    malos = [v for v in verifs if v.estado == "no cumple"]
    alertas = [v for v in verifs if v.estado == "alerta"]
    if not res.convergio:
        return ["El flujo de cargas no convergió; revise el modelo antes de interpretar resultados."]
    if not malos:
        out.append("Todos los criterios verificados se cumplen en el escenario "
                   f"'{res.escenario}'.")
    for v in malos:
        out.append(f"NO CUMPLE — {v.criterio} en {v.elemento}: {_f(v.valor)} {v.unidad} "
                   f"(límite {v.limite} {v.unidad}, {v.norma}).")
    for v in alertas:
        out.append(f"EN EL LÍMITE — {v.criterio} en {v.elemento}: {_f(v.valor)} {v.unidad} "
                   f"(límite {v.limite} {v.unidad}).")
    if res.perdidas_totales_kW is not None:
        out.append(f"Pérdidas totales del sistema: {_f(res.perdidas_totales_kW)} kW.")
    if red.supuestos():
        out.append(f"El modelo contiene {len(red.supuestos())} datos supuestos o deducidos "
                   "(Sección 3); las conclusiones son válidas solo si se confirman.")
    return out


def generar(red: Red, resultados: dict[str, Resultados], salida: str | Path,
            cruces: list[tuple[Resultados, Resultados]] | None = None,
            textos: dict[str, str] | None = None, carpeta_figuras: str | Path | None = None) -> Path:
    """resultados: escenario -> Resultados (de la herramienta principal)."""
    textos = textos or {}
    salida = Path(salida)
    figs = Path(carpeta_figuras or salida.parent / "figuras")
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.2)
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)

    principal = next(iter(resultados.values()))

    # ---------- portada ----------
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("INFORME TÉCNICO\nEstudio de flujo de cargas")
    r.bold = True
    r.font.size = Pt(20)
    doc.add_paragraph()
    _tabla(doc, ["Campo", "Valor"], [
        ["Proyecto", red.proyecto],
        ["Herramienta de cálculo", principal.herramienta],
        ["Escenarios", ", ".join(resultados)],
        ["Método", "Newton-Raphson, AC balanceado"],
        ["Elaborado por", red.autor or "—"],
        ["Fecha", dt.date.today().isoformat()],
        ["Revisión", "0 (borrador generado automáticamente)"],
    ])
    aviso = doc.add_paragraph()
    ra = aviso.add_run("Este documento debe ser revisado y firmado por un ingeniero electricista con "
                       "matrícula profesional vigente antes de su radicación.")
    ra.italic = True
    ra.font.color.rgb = RGBColor(0x90, 0x00, 0x00)
    doc.add_page_break()

    # ---------- 1. objetivo ----------
    doc.add_heading("1. Introducción y objetivo", 1)
    doc.add_paragraph(textos.get("introduccion") or
                      "Determinar tensiones, flujos, cargabilidad y pérdidas del sistema, y verificar "
                      "su cumplimiento frente a la NTC 1340, la NTC 2050 y el RETIE.")

    # ---------- 2. sistema ----------
    doc.add_heading("2. Descripción del sistema", 1)
    doc.add_paragraph(red.descripcion.strip())
    doc.add_heading("2.1 Barras", 2)
    _tabla(doc, ["Barra", "Tensión nominal [kV]"], [[b.etiqueta, _f(b.un_kV, 3)] for b in red.barras])
    if red.lineas:
        doc.add_heading("2.2 Líneas y cables", 2)
        _tabla(doc, ["Elemento", "Desde → hasta", "Conductor", "L [m]", "R [Ω/km]", "X [Ω/km]",
                     "In [A]", "Origen"],
               [[l.etiqueta, f"{l.desde} → {l.hasta}", l.conductor or "—", _f(l.longitud_km * 1000, 0),
                 f"{_f(l.r_ohm_km, 3)} @{l.temperatura_ref_C:g}°C", _f(l.x_ohm_km, 3),
                 _f(l.in_kA * 1000, 0), l.origen] for l in red.lineas])
    if red.transformadores:
        doc.add_heading("2.3 Transformadores", 2)
        _tabla(doc, ["Elemento", "S [kVA]", "Tensiones [kV]", "uk [%]", "Pcu [kW]", "Grupo", "Origen"],
               [[t.etiqueta, _f(t.sn_MVA * 1000, 0), f"{t.un_at_kV:g}/{t.un_bt_kV:g}", _f(t.uk_pct),
                 _f(t.pcu_kW), t.grupo, t.origen] for t in red.transformadores])
    if red.cargas or red.generadores_pv:
        doc.add_heading("2.4 Cargas y generación", 2)
        _tabla(doc, ["Elemento", "Barra", "P [kW]", "Q [kvar]", "Origen"],
               [[c.etiqueta, c.barra, _f(c.p_MW * 1000, 1), _f(c.q_Mvar * 1000, 1), c.origen]
                for c in red.cargas + red.generadores_pv])

    # ---------- 3. supuestos ----------
    doc.add_heading("3. Datos supuestos y deducidos", 1)
    sup = red.supuestos()
    if sup:
        doc.add_paragraph("Los siguientes datos no provienen de planos ni placas y deben confirmarse:")
        for s in sup:
            doc.add_paragraph(s, style="List Bullet")
    else:
        doc.add_paragraph("Todos los datos del modelo provienen de fuentes documentadas.")

    # ---------- 4. resultados por escenario ----------
    doc.add_heading("4. Resultados", 1)
    todas: dict[str, list[Verificacion]] = {}
    for n, (esc_id, res) in enumerate(resultados.items(), start=1):
        esc = red.escenario(esc_id)
        doc.add_heading(f"4.{n} Escenario '{esc_id}' — {esc.descripcion}", 2)
        doc.add_paragraph(f"Temperatura de cálculo de conductores: {esc.temperatura_C:g} °C. "
                          f"Escala de carga: {esc.escala_carga:g}. "
                          f"Convergió: {'sí' if res.convergio else 'NO'}"
                          + (f" en {res.iteraciones} iteraciones." if res.iteraciones else "."))
        fig = dibujar(red, res, figs / f"unifilar_{esc_id}")
        doc.add_picture(str([f for f in fig if f.suffix == ".png"][0]), width=Cm(15))
        cap = doc.add_paragraph(f"Figura {n}. Diagrama unifilar con resultados, escenario '{esc_id}'.")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.runs[0].italic = True
        _tabla(doc, ["Barra", "U [kV]", "u [p.u.]", "Ángulo [°]"],
               [[red.barra(b).etiqueta, _f(r.ul_kV, 4), _f(r.u_pu, 4), _f(r.angulo_deg, 2)]
                for b, r in res.barras.items()])
        _tabla(doc, ["Rama", "P [kW]", "Q [kvar]", "I emisor [A]", "I receptor [A]", "Carga [%]", "Pérdidas [kW]"],
               [[rid, _f(r.p_MW * 1000), _f(r.q_Mvar * 1000), _f(r.i_kA * 1000, 1),
                 _f((r.i_kA_receptor or 0) * 1000, 1), _f(r.cargabilidad_pct, 1), _f(r.perdidas_kW, 3)]
                for rid, r in res.ramas.items()])
        v = verificar(red, res)
        todas[esc_id] = v
        doc.add_paragraph("Verificación normativa:").runs[0].bold = True
        _tabla(doc, ["Criterio", "Norma", "Elemento", "Valor", "Límite", "Estado"],
               [[x.criterio, x.norma, x.elemento, f"{_f(x.valor)} {x.unidad}", f"{x.limite} {x.unidad}",
                 x.estado.upper()] for x in v], estados=[x.estado for x in v])
        if res.cortocircuito:
            _tabla(doc, ["Barra", "Ik'' [kA]", "Sk'' [MVA]", "ip [kA]"],
                   [[b, _f(c.ikss_kA, 3), _f(c.skss_MVA, 2), _f(c.ip_kA or 0, 3)]
                    for b, c in res.cortocircuito.items()])
        nombres = {"1f": "monofásica a tierra", "2f": "bifásica", "2ft": "bifásica a tierra"}
        for tipo, por_barra in res.fallas.items():
            doc.add_paragraph(f"Falla {nombres.get(tipo, tipo)} (IEC 60909, máxima):").runs[0].bold = True
            _tabla(doc, ["Barra", "Ik'' [kA]", "ip [kA]"],
                   [[b, _f(c.ikss_kA, 3), _f(c.ip_kA or 0, 3)] for b, c in por_barra.items()])

    # ---------- 5. comparación de escenarios ----------
    if len(resultados) > 1:
        doc.add_heading("5. Comparación de escenarios", 1)
        ids = list(resultados)
        _tabla(doc, ["Barra"] + [f"u [p.u.] {e}" for e in ids],
               [[red.barra(b.id).etiqueta] + [_f(resultados[e].barras[b.id].u_pu, 4)
                                              if b.id in resultados[e].barras else "—" for e in ids]
                for b in red.barras])

    # ---------- 6. validación cruzada ----------
    if cruces:
        doc.add_heading("6. Validación cruzada entre herramientas", 1)
        for a, b in cruces:
            dif = comparar(a, b)
            doc.add_paragraph(f"{a.herramienta} vs {b.herramienta} (escenario {a.escenario}): " +
                              ("coinciden dentro de tolerancia (Δu ≤ 0,005 p.u., Δcarga ≤ 2 %)."
                               if not dif else "diferencias: " + "; ".join(dif)))
            _tabla(doc, ["Barra", f"u {a.herramienta}", f"u {b.herramienta}", "Δu [p.u.]"],
                   [[bid, _f(ra.u_pu, 4), _f(b.barras[bid].u_pu, 4), _f(ra.u_pu - b.barras[bid].u_pu, 4)]
                    for bid, ra in a.barras.items() if bid in b.barras])

    # ---------- 7. análisis y conclusiones ----------
    doc.add_heading("7. Análisis y conclusiones", 1)
    if textos.get("analisis"):
        for par in textos["analisis"].split("\n\n"):
            doc.add_paragraph(par.strip())
    for esc_id, res in resultados.items():
        rs = resumen(todas[esc_id])
        doc.add_paragraph(f"Escenario '{esc_id}' — {rs['cumple']} criterios cumplen, {rs['alerta']} en "
                          f"alerta, {rs['no cumple']} no cumplen:").runs[0].bold = True
        for c in conclusiones_automaticas(red, res, todas[esc_id]):
            doc.add_paragraph(c, style="List Bullet")
    if textos.get("conclusiones"):
        doc.add_heading("Recomendaciones", 2)
        for par in textos["conclusiones"].split("\n"):
            if par.strip():
                doc.add_paragraph(par.strip().lstrip("-• "), style="List Number")

    salida.parent.mkdir(parents=True, exist_ok=True)
    doc.save(salida)
    return salida
