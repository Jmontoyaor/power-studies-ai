# Herramientas: cómo se automatiza cada una y cómo se logra la parte gráfica

| Herramienta | Vía de automatización | Construye el modelo | Corre la simulación | Parte gráfica | Requisito |
|---|---|---|---|---|---|
| **pandapower** | Python | sí | sí (flujo, cortocircuito IEC 60909) | unifilar propio con resultados (`power_studies/diagrama.py`) | ninguno |
| **OpenDSS** | `opendssdirect.py` + script `.dss` | sí | sí (flujo) | unifilar propio | ninguno |
| **PowerFactory** | API Python oficial (`powerfactory`) | sí (`pf_construir_red.py`) | sí (ComLdf, ComShc) | auto-diagramado de PF; si no existe, símbolos ubicados con las posiciones del modelo | Windows + licencia con Python |
| **ATP / ATPDraw** | archivo `.atp` (texto en columnas) | por plantilla | sí, en lote con `tpbig`/`runATP` | el dibujo de ATPDraw del ingeniero (la plantilla) | ATP instalado |
| **ETAP** | importación de datos (Excel/DataX) o API según licencia | tablas generadas | en ETAP | ETAP ubica los elementos importados; acomodo manual | ETAP; verificar módulo de importación/API de su licencia |
| **PVsyst** | modo *Batch* sobre un proyecto plantilla | parámetros por CSV | en PVsyst | reportes y diagramas propios de PVsyst | PVsyst con modo batch |

## Por qué plantillas para ATP, ETAP y PVsyst

Estas herramientas no exponen una API abierta y estable para **dibujar** desde
cero. La forma confiable de tener "modelo + simulación + gráfica" es que el
ingeniero dibuje una vez el caso tipo, con sus símbolos, y lo marque con
variables `{{...}}`. El adaptador produce una copia por estudio y escenario. Si
la topología cambia mucho, se hace una plantilla nueva.

### ATP

1. Dibuje el caso en ATPDraw y genere el `.atp` (*ATP → Make File*).
2. En el `.atp`, reemplace cada número a parametrizar por `{{VARIABLE|ancho}}`,
   donde `ancho` es el ancho de la columna (p. ej. 6 para R y L en tarjetas de rama).
   Escriba la línea como si el campo midiera exactamente ese ancho.
3. Vea las variables disponibles: `power-studies exportar red.yaml --herramienta atp --salida x`
   (archivo `variables_atp.csv`).
4. Genere: `power-studies exportar red.yaml --herramienta atp --salida x --plantilla mi_caso.atp`.
5. Con `ATP_EXE` definido, el agente puede correr ATP en lote y leer el `.pl4`.

Ejemplo: `plantillas/atp/falla_3f_ejemplo.atp`.

### ETAP

`etap_importacion.xlsx` trae una hoja por tipo de elemento (Buses, Utilities,
Cables, Transformers, Loads) con las posiciones del unifilar. Las columnas exactas
del importador cambian entre versiones de ETAP: ajústelas una vez a su versión
y queda resuelto para todos los estudios.

### PVsyst

`pvsyst_batch.csv` lista los generadores FV del modelo para el modo *Batch*
sobre una variante plantilla del ingeniero. PVsyst produce sus propios reportes.

## Agregar una herramienta

1. Subclase de `power_studies.adaptadores.base.Adaptador` con `flujo()` y/o `exportar()`.
2. Regístrela en `power_studies/adaptadores/__init__.py`.
3. Prueba en `tests/` que reproduzca `casos/ejemplo_4_barras` (E1, E2, E3).
