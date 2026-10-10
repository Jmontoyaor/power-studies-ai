# Resumen: lo que llevamos y lo que esperamos

Estado al **10 de octubre de 2026**. Este archivo se actualiza con cada entrega; el
detalle técnico de cada paso está en la [hoja de ruta](hoja_de_ruta.md).

## En una línea

Desde un `red.yaml` el proyecto ya calcula flujo, cortocircuito (3F, 2F, 1F, 2FT), malla de
puesta a tierra, banco de baterías con su cargador y configuraciones de subestación; dibuja
en ATPDraw y AutoCAD; y arma el informe en LaTeX/PDF. Todo validado contra ejemplos de las
normas, con 130 pruebas.

## Lo que llevamos

| Fecha | Entrega | PR | Validación |
|---|---|---|---|
| 2026-10-09 | Proyecto de ATPDraw **dibujado** desde `red.yaml` (XML de ATPDraw 7.8) | #1 | caso de 4 barras = Newton-Raphson del informe |
| 2026-10-09 | ATPDraw: grupos de conexión (Dyn5), capacitancia de líneas, falla 3F | #1 | 75 kVA = pandapower en magnitud y ángulo |
| 2026-10-09 | Fallas asimétricas 1F, 2F, 2FT con secuencia cero | #2 | componentes simétricas a mano (Δ ≤ 0,01 %) |
| 2026-10-09 | Malla de puesta a tierra IEEE 80-2013 | #2 | ejemplos B.1, B.2 y B.3 del Anexo B |
| 2026-10-10 | Banco de baterías IEEE 485-2020 y cargador IEEE 946-2020 | #3 | Figura A.1 (485); ejemplos B.3 y B.4 (946) |
| 2026-10-10 | Configuraciones de subestación, confiabilidad y unifilar | #3 | propiedades de las 6 configuraciones |
| 2026-10-10 | Planos para AutoCAD (DXF) | #4 | DXF auditado; longitudes y equipos verificados |
| 2026-10-10 | Informe LaTeX/PDF que decide sus secciones | #5 | compila en las pruebas |
| 2026-10-10 | README reescrito | #6 | enlaces y comandos verificados |
| 2026-10-10 | Catálogo de 257 componentes de ATPDraw con retroalimentación automática | #7 | el adaptador escribe el formato real de ATPDraw |

### Hallazgos que conviene recordar

- **ATP contra IEC 60909 en BT:** la diferencia (+2,3 % en el 75 kVA) es el factor K_T que
  IEC aplica a los transformadores de red; ATP da la corriente física. No se ajusta.
- **Cargas en ATP:** son de impedancia constante; el flujo de cargas usa potencia constante.
  Con la impedancia a la tensión de operación, ATP reproduce el flujo exacto.
- **Erratas de las normas** (anotadas en las pruebas): IEEE 485 Figura A.1, sección 3, dice
  T = 1 min para un periodo de 30 min; IEEE 946 ecuación B.6 dice I₂ donde va I₃.
- **IEEE 80:** la columna TCAP de la Tabla 1 no se extrae bien del PDF; el calibre usa la
  Tabla 2 (Kf), igual que el ejemplo de la norma.

## Lo que esperamos

### Entregas del curso de Subestaciones

| Entrega | Peso | Estado |
|---|---|---|
| Malla de puesta a tierra | 5 % | ✅ herramienta lista; faltan los datos reales (sondeos del 13 al 20 de oct., entrega 27 de oct.) |
| Banco de baterías y cargador | 10 % | ✅ herramienta lista; falta el ciclo de trabajo de la subestación del curso |
| Diagrama unifilar | 5 % | ✅ herramienta lista (PNG, SVG, PDF y DXF) |
| Control, protección y medida de una bahía | 20 % | ⏳ espera la guía del profesor y el tipo de bahía |

### Próximos pasos de la herramienta

1. **Protecciones** (paso 3): relés 50/51 y 50N/51N con curvas IEC/IEEE, TC/TP y
   coordinación; validar contra el informe de coordinación del 75 kVA. Es la base de la
   entrega de la bahía.
2. **Importador ATPDraw → `red.yaml`**: pasar proyectos ya dibujados al modelo neutro.
3. **Transitorios en ATP** (paso 7): rayo sobre torre y malla de alta frecuencia, usando el
   catálogo (Heidler, LCC, LINEZT, MOV) y el proyecto de 2026-1 como validación.
4. **Análisis de Sistemas de Potencia** (pasos 4 y 5): generadores, despacho, OPF y
   estimación de estado contra IEEE 14 barras en MATPOWER.
5. Distribución desbalanceada con OpenDSS y estabilidad (pasos 6 y 8).

### Pendientes de datos

- Potencia de cortocircuito trifásica y **monofásica** en el PCC del 75 kVA (operador de red).
- Secuencia cero real de los cables (ficha del fabricante); hoy es la regla Z0 ≈ 3·Z1.
- Resistividad del terreno de la subestación del curso (sondeos).

## Cómo mantener este resumen

Al cerrar una entrega: agregue una fila a «Lo que llevamos» (fecha, PR, validación), mueva
lo terminado fuera de «Lo que esperamos» y anote en «Hallazgos» cualquier diferencia
explicada o errata encontrada.
