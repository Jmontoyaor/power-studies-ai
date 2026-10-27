# Retroalimentación: el proyecto aprende de sus archivos

Cada vez que se usa `power-studies`, el proyecto revisa las carpetas de
`retroalimentacion/` y aprende de los archivos nuevos o modificados de cada programa.
Así el conocimiento crece con el uso, en vez de redescubrir cada formato.

## Uso

1. Deje el archivo en la carpeta del programa:

   | Carpeta | Qué dejar | Qué se aprende | Para qué sirve |
   |---|---|---|---|
   | `retroalimentacion/atpdraw/` | proyectos guardados como XML (*Save As → XML text format*) | plantilla de cada componente | el adaptador dibuja cualquier componente sin investigar su formato |
   | `retroalimentacion/opendss/` | scripts `.dss` | clases de elementos, propiedades y valores típicos | ampliar el adaptador de OpenDSS; valores de referencia (LineCode, transformadores) |
   | `retroalimentacion/autocad/` | planos `.dxf` (*Guardar como → DXF*) | capas, bloques de símbolos con atributos, estilos de texto, unidades | que los DXF generados sigan las capas y bloques de sus planos |
   | `retroalimentacion/powerfactory/` | exportes `.dgs`, `.csv`, `.xlsx` | tablas y columnas | alinear el importador de PowerFactory |
   | `retroalimentacion/etap/` | plantillas de importación `.xlsx`/`.csv` de su versión | hojas y columnas exactas | ajustar las tablas que genera el adaptador de ETAP |
   | `retroalimentacion/pvsyst/` | `.PAN` (módulos), `.OND` (inversores), exportes `.csv` | parámetros y columnas | datos de módulos e inversores para generación FV |

2. Use el software como siempre. Al empezar cualquier comando aparece, si hubo algo nuevo:
   ```
   [retroalimentación] opendss: 1 archivo(s) nuevo(s); aprendió 4: Circuit, Line, Transformer, Load
   ```
3. Consulte lo aprendido:
   ```bash
   power-studies conocimiento                    # resumen por programa
   power-studies conocimiento opendss            # clases aprendidas
   power-studies conocimiento opendss Transformer
   power-studies conocimiento atpdraw LCC
   power-studies retroalimentar                  # procesar ya, sin otro comando
   ```

Carpetas fuera del repo, con la misma estructura de subcarpetas, se agregan con la variable
de entorno `POWER_STUDIES_RETRO` (rutas separadas por `;` en Windows).

## Cómo funciona

- **Incremental:** cada archivo se identifica por su huella SHA-256
  (`power_studies/conocimiento/_indice.json`); solo se relee si cambió.
- **Acumulativo:** lo aprendido se guarda en `power_studies/conocimiento/<programa>.json`
  (ATPDraw en `adaptadores/atpdraw_catalogo.json`) y se versiona en git, así que lo que se
  aprende en un equipo sirve en los demás.
- **Tolerante:** un archivo dañado se reporta y no detiene el comando.
- **Formatos binarios** (`.acp` de ATPDraw, `.pfd` de PowerFactory, `.dwg` de AutoCAD) no se
  leen: use la exportación de texto de cada programa.

## Límite importante

Lo aprendido describe **formatos y valores de referencia**. Usarlo en un cálculo exige la
misma validación que el resto del proyecto: un componente o una tabla nueva entra al
cálculo con su caso de validación y su prueba (ver `AGENTS.md`).

## Agregar un programa

En `power_studies/retroalimentacion.py`, escriba una función `aprender_<programa>(ruta, k)`
que actualice el diccionario `k` y devuelva lo nuevo, y regístrela en `APRENDICES` con sus
extensiones. Agregue una prueba en `tests/test_retroalimentacion.py`.
