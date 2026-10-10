# AGENTS.md — Reglas del proyecto power-studies-ai

Este archivo lo leen Claude Code, OpenCode y otros asistentes. Define cómo
se trabaja un estudio eléctrico con agentes.

## Principios (no negociables)

1. **El modelo neutro (`modelo/red.yaml`) es la única fuente de verdad.**
   Ningún agente edita a mano un archivo de PowerFactory, ATP, ETAP o PVsyst:
   se edita el modelo y se regenera con `power-studies exportar`.
2. **Nada se inventa en silencio.** Todo dato que no salga de un plano, una
   placa, una ficha técnica o el proyecto original va con
   `origen: supuesto` o `origen: deducido` y una `nota` que explique de dónde
   salió. El informe los lista solo.
3. **Los números los calcula el código, no el modelo de lenguaje.** Los agentes
   nunca escriben resultados "de memoria" en un informe: corren
   `power-studies simular/verificar/informe` y citan esos resultados.
4. **Toda herramienta nueva se valida** contra `casos/ejemplo_4_barras`
   (Newton-Raphson verificado) y contra pandapower/OpenDSS antes de usarse en
   un estudio real (`power-studies comparar`).
5. **Puertas de aprobación humana.** El flujo se detiene al final de cada fase y
   espera el visto bueno del ingeniero. La firma del estudio es siempre humana.
6. Idioma de trabajo y de los informes: **español técnico colombiano**. Normas de
   referencia: RETIE, NTC 1340, NTC 2050, NTC 818/819, resoluciones CREG y la
   norma del operador de red del proyecto.

## Estructura de un estudio

```
estudios/<id>/
├── ESTADO.md          # tabla de fases y gates (la actualiza el coordinador)
├── insumos/           # lo que entrega el ingeniero: planos, fichas, .pfd, exportes
├── modelo/red.yaml    # modelo neutro
├── resultados/        # resultados_<herramienta>_<escenario>.json
├── herramientas/      # archivos para PowerFactory, ATP, ETAP, PVsyst
└── informe/           # textos.yaml, figuras/, informe.docx
```

Se crea con `power-studies nuevo estudios/<id> [--desde casos/.../red.yaml]`.

## Pipeline y agentes

| Fase | Agente | Entrega | Gate |
|---|---|---|---|
| 0 Insumos | `lector-insumos` | inventario de datos + lista de faltantes | G0: ¿insumos suficientes? |
| 1 Modelo | `modelador` | `modelo/red.yaml` válido + escenarios | G1: ingeniero aprueba topología, parámetros y supuestos |
| 2 Simulación | `simulador` | resultados por escenario + validación cruzada pandapower/OpenDSS | G2: ¿resultados físicamente coherentes? |
| 3 Verificación | `analista-normativo` | verificación NTC/RETIE + escenarios de mejora | G3: ¿alternativas aceptadas? |
| 4 Herramientas | `integrador-herramientas` | modelo en PowerFactory/ATP/ETAP/PVsyst con unifilar + comparación | G4: ¿coinciden las herramientas? |
| 5 Informe | `redactor-informe` → `revisor` | `informe/informe.docx` + veredicto del revisor | G5: revisión final y firma |

La Fase 4 es opcional (solo si el cliente exige una herramienta comercial) y
requiere el equipo Windows con la licencia: ver `docs/powerfactory.md`.

## Comandos de la CLI que usan los agentes

```bash
power-studies herramientas                       # qué hay disponible en este equipo
power-studies validar modelo/red.yaml            # integridad + lista de supuestos
power-studies simular modelo/red.yaml --escenario todos --cortocircuito --salida resultados
power-studies comparar modelo/red.yaml --herramientas pandapower,opendss
power-studies verificar modelo/red.yaml --resultados resultados/resultados_pandapower_base.json
power-studies unifilar modelo/red.yaml --resultados <json> --salida informe/figuras/unifilar
power-studies exportar modelo/red.yaml --herramienta powerfactory --salida herramientas/powerfactory
power-studies importar-pf insumos/modelo_neutro.json --salida modelo/red.yaml
power-studies informe modelo/red.yaml --escenario todos --cruce opendss --cortocircuito \
    --textos informe/textos.yaml --salida informe/informe.docx
```

Código de salida 2 = discrepancia con la referencia o entre herramientas:
detenerse y reportar, nunca "ajustar" números para que cuadren.

## Retroalimentación de herramientas

- **ATPDraw**: todo proyecto de ATPDraw que se use o revise en un estudio se guarda también
  como XML (*Save As → XML text format*) en `atpdraw/proyectos_xml/`. El catálogo de
  componentes aprende de él solo la próxima vez que se use `power-studies` con ATPDraw.
  Antes de agregar un componente al adaptador, consulte `power-studies atpdraw-catalogo NOMBRE`
  en vez de investigar el formato. Guía: `docs/atpdraw.md`.
- **Normas**: las erratas o detalles encontrados al validar contra un ejemplo de norma se
  anotan en la prueba correspondiente y en `docs/RESUMEN.md`.

## Desarrollo del marco

- `python -m pytest` debe pasar antes de cada commit.
- Adaptador nuevo: subclase de `power_studies.adaptadores.base.Adaptador`,
  registro en `adaptadores/__init__.py`, prueba en `tests/` contra el caso de 4 barras.
- Los scripts de `herramientas/powerfactory/` solo usan la biblioteca estándar
  (corren con el Python de PowerFactory) y se prueban con `tests/fake_powerfactory.py`.
