# Herramientas: cómo se automatiza cada una y cómo se logra la parte gráfica

| Herramienta | Vía de automatización | Construye el modelo | Corre la simulación | Parte gráfica | Requisito |
|---|---|---|---|---|---|
| **pandapower** | Python | sí | sí (flujo, cortocircuito IEC 60909) | unifilar propio con resultados (`power_studies/diagrama.py`) | ninguno |
| **OpenDSS** | `opendssdirect.py` + script `.dss` | sí | sí (flujo) | unifilar propio | ninguno |
| **PowerFactory** | API Python oficial (`powerfactory`) | sí (`pf_construir_red.py`) | sí (ComLdf, ComShc) | auto-diagramado de PF; si no existe, símbolos ubicados con las posiciones del modelo | Windows + licencia con Python |
| **ATPDraw** | proyecto XML de ATPDraw (≥ 7.0) | sí (`atpdraw_ad.py`) | sí, ATP desde ATPDraw (F2) | dibujado por el adaptador desde `red.yaml` | ATPDraw ≥ 7.0 + ATP |
| **ATP (plantilla)** | archivo `.atp` (texto en columnas) | por plantilla | sí, en lote con `tpbig`/`runATP` | el dibujo de ATPDraw del ingeniero (la plantilla) | ATP instalado |
| **ETAP** | importación de datos (Excel/DataX) o API según licencia | tablas generadas | en ETAP | ETAP ubica los elementos importados; acomodo manual | ETAP; verificar módulo de importación/API de su licencia |
| **PVsyst** | modo *Batch* sobre un proyecto plantilla | parámetros por CSV | en PVsyst | reportes y diagramas propios de PVsyst | PVsyst con modo batch |

## Por qué plantillas para ATP, ETAP y PVsyst

Estas herramientas no exponen una API abierta y estable para **dibujar** desde
cero. La forma confiable de tener "modelo + simulación + gráfica" es que el
ingeniero dibuje una vez el caso tipo, con sus símbolos, y lo marque con
variables `{{...}}`. El adaptador produce una copia por estudio y escenario. Si
la topología cambia mucho, se hace una plantilla nueva.

### ATPDraw (dibujo automático)

ATPDraw abre proyectos en formato XML ("XML text format", desde la versión 7.0).
`power-studies exportar red.yaml --herramienta atpdraw --salida x` escribe ese XML
con cada elemento dibujado, conectado y con los nombres de barra del modelo.

1. Abra el `.xml` en ATPDraw (File → Open). Si quiere, guárdelo como `.acp`.
2. Corra ATP con F2. Las sondas de cada barra piden la solución de régimen permanente.
3. `leer_lis(ruta.lis, red)` devuelve las tensiones de barra en p.u.

Reglas del formato (verificadas con ATPDraw 7.8): la conectividad es por
coordenadas (múltiplos de 10) o cables `<conn>`; los nombres de nodo se conservan
solo con `UserNamed="true"`; tierra = `Ground="1"`; nombre base ≤ 5 caracteres.

Modelo: fuente ideal en la barra slack; líneas R+L serie o PI trifásico si
tienen capacitancia; transformador SATTRAFO con su grupo y desfase (Dyn5, YNd11,
Yy0...; `Coupl = tipo·1000 + desfase`, tipo 1 = Y y 2 = D); cargas como
impedancia constante.

Cortocircuito trifásico: `exportar(..., falla_3f="BARRA")` agrega la impedancia
de la red Zq = c·Un²/Scc, sube la fuente a c·Un (c = 1,1), quita las cargas y pone
una falla franca en la barra; `leer_falla(ruta.lis, red, barra)` devuelve Ik'' en kA.

Validación (`tests/test_atpdraw.py`, con salidas reales de ATP en `tests/datos/`):

| Caso | Resultado |
|---|---|
| 4 barras, flujo E1 | igual al Newton-Raphson del informe (Δu ≤ 0,0001 p.u.) con cargas calculadas a la tensión de operación |
| 75 kVA, flujo base | igual a pandapower en magnitud y ángulo (BT a −151,04°: el Dyn5 queda bien) |
| 75 kVA, falla 3F en PCC y MT | igual a pandapower IEC 60909 (Δ < 0,1 %) |
| 75 kVA, falla 3F en BT y TGD | ATP +2,3 % y +1,7 % sobre IEC 60909 |

Las diferencias que quedan son de método, no de red:

- **Carga:** ATP usa impedancia constante; el flujo de cargas usa potencia
  constante. Con la impedancia a tensión nominal, la BT queda unas milésimas de
  p.u. más alta.
- **Cortocircuito en BT:** IEC 60909 multiplica la impedancia de los
  transformadores de red por K_T = 0,95·c/(1+0,6·x_T) (≈ 1,025 para el TR1); ATP
  calcula la corriente física sin ese factor. La prueba lo comprueba con el
  cálculo a mano. No se agrega K_T a ATP para que "cuadre".

Pendiente: grupos zigzag, transformadores de tres devanados, redes malladas en
el dibujo, fallas asimétricas (paso 2 de `docs/hoja_de_ruta.md`).

### ATP (plantilla)

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
