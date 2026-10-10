# ATPDraw: cómo trabaja power-studies y cómo ampliarlo

power-studies genera proyectos de ATPDraw **ya dibujados** desde `red.yaml`, sin plantillas
hechas a mano. Este documento reúne lo necesario para usarlo y, sobre todo, para
**agregar componentes nuevos sin investigar el formato de ATPDraw**.

## Uso (Windows)

1. Genere el proyecto:
   ```bash
   power-studies exportar red.yaml --herramienta atpdraw --salida atp/
   ```
2. Ábralo en ATPDraw (≥ 7.0) con *File → Open* (`.xml`). Si quiere, guárdelo como `.acp`.
3. Corra ATP con **F2**. Las sondas de cada barra piden la solución de régimen permanente.
4. Lea los resultados desde Python con `leer_lis(ruta.lis, red)` (tensiones) o
   `leer_falla(ruta.lis, red, barra)` (corriente de falla).

Para fallas: `exportar(..., falla="BARRA", tipo_falla="3f" | "1f" | "2f" | "2ft")`.

## El formato, en una tabla

ATPDraw guarda proyectos en XML (*File → Save As → XML text format*). Lo que hay que
respetar al generarlos:

| Regla | Detalle |
|---|---|
| Conectividad por geometría | dos terminales están unidos si coinciden en coordenadas o los une un `<conn>`; coordenadas en múltiplos de 10 |
| Nombres de nodo | se conservan solo con `UserNamed="true"`; base de ≤ 5 caracteres (ATPDraw agrega A/B/C) |
| Tierra | atributo `Ground="1"` en el terminal |
| Transformador SATTRAFO | `Coupl = tipo·1000 + desfase` (1 = Y, 2 = D); tensión de devanado de línea en D y de fase en Y |
| Fuente ACSOURCE | `Phases=1` trifásica; `Scaling=2` amplitud en V eficaces de línea |
| Unidades | con `XOPT=0` y `COPT=0` en el encabezado, L en mH y C en µF |

## El catálogo de componentes

`power_studies/adaptadores/atpdraw_catalogo.json` tiene la plantilla de **cada componente
de ATPDraw** (terminales con fases y posición, datos con unidades y valores de ejemplo,
estructuras extra), aprendida de los proyectos de ejemplo de ATPDraw y de proyectos propios.

```bash
power-studies atpdraw-catalogo            # lista los componentes
power-studies atpdraw-catalogo LCC        # ficha de un componente
```

Desde Python, cualquier componente se coloca así:

```python
from power_studies.atpdraw_catalogo import componente
c = componente("HEIDLER", 2800, 2700, nodos={"HEI": "TOPE"},
               datos={"Amplitude": 31000, "T_f": 1.2e-6, "tau": 5e-5})
```

Si un nombre de dato o terminal no existe, el error lista los válidos.

### Ampliar el catálogo (retroalimentación automática)

1. En ATPDraw abra el proyecto y haga *File → Save As → XML text format*.
2. Guarde el `.xml` en `atpdraw/proyectos_xml/` del repo (o en una carpeta listada en la
   variable de entorno `POWER_STUDIES_ATPDRAW`, separadas por `;` en Windows).
3. Listo: la próxima vez que use `exportar --herramienta atpdraw` o `atpdraw-catalogo`,
   el proyecto se incorpora solo y se avisa qué componentes nuevos aprendió.

Es incremental: cada archivo se identifica por su huella SHA-256 y solo se vuelve a leer
si cambió. Para una carpeta suelta también sirve
`power-studies atpdraw-catalogo --construir carpeta_con_xml`.

Para tener **todos** los componentes de ATPDraw basta con el proyecto `All.acp` que trae
ATPDraw en su carpeta `Projects`.

## Agregar un componente al adaptador

1. Mire su ficha: `power-studies atpdraw-catalogo NOMBRE`.
2. En `adaptadores/atpdraw_ad.py`, colóquelo con `componente(...)` y únalo con `lz.cable(...)`
   a los terminales vecinos (la posición de cada terminal es la del componente más el
   `PosX/PosY` relativo de la ficha).
3. Agregue a `tests/test_atpdraw_catalogo.py` un caso que lo use: la prueba
   `test_el_adaptador_escribe_el_formato_real_de_atpdraw` verifica que los terminales y
   datos coincidan con el catálogo.
4. **Valide el modelo eléctrico**: ábralo en ATPDraw, corra ATP y compare con un cálculo
   independiente; guarde el `.lis` en `tests/datos/` y escriba la prueba. El catálogo
   asegura el formato, no que el componente esté bien usado.

## Correr ATP sin ATPDraw

`tpbig` corre sin interacción: `tpbigm.exe both caso.atp caso. -R`. Los `.atp` que
genera ATPDraw pueden traer rutas absolutas en `$INSERT` (archivos `.pch` de las LCC):
deben existir en el equipo donde se corre.
