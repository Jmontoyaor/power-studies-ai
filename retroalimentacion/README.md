# Retroalimentación

Cada vez que se usa `power-studies`, los archivos nuevos o modificados de estas carpetas se procesan y lo aprendido queda en `power_studies/conocimiento/` (`power-studies conocimiento`).

| Carpeta | Qué dejar | Qué se aprende |
|---|---|---|
| `atpdraw/` | proyectos de ATPDraw guardados como XML (File → Save As → XML text format) | la plantilla de cada componente; el adaptador la usa para dibujar |
| `opendss/` | scripts `.dss` de OpenDSS | clases de elementos, propiedades y valores típicos (líneas, LineCode, transformadores, cargas...) |
| `autocad/` | planos `.dxf` (en AutoCAD: Guardar como → DXF) | capas, bloques de símbolos con sus atributos, estilos de texto y unidades |
| `powerfactory/` | exportes `.dgs`, `.csv` o `.xlsx` de PowerFactory | tablas y columnas de los exportes, para alinear el importador |
| `etap/` | plantillas de importación `.xlsx`/`.csv` de su versión de ETAP | hojas y columnas exactas que espera su ETAP |
| `pvsyst/` | archivos `.PAN` (módulos), `.OND` (inversores) y exportes `.csv` | parámetros de módulos e inversores y columnas de exportes |

Otras carpetas con la misma estructura se agregan con la variable de entorno `POWER_STUDIES_RETRO` (rutas separadas por `;` en Windows). Detalle: [`docs/retroalimentacion.md`](../docs/retroalimentacion.md).
