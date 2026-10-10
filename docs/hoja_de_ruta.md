# Hoja de ruta: de flujo de cargas a todas las áreas de potencia

Meta: usar `power-studies-ai` en protecciones, distribución, generación,
subestaciones, análisis de sistemas de potencia y transmisión, con el mismo
principio de siempre: **un modelo neutro (`red.yaml`) y un adaptador por herramienta**.

## Reglas para cada paso

1. **Diseñar antes de programar.** Si el paso agrega elementos a `red.yaml`
   (generadores, relés, geometría de líneas…), primero se acuerda el esquema,
   porque afecta a todos los adaptadores.
2. **Nada entra sin su caso de validación** en `casos/` y su prueba en `tests/`:
   un ejemplo de libro, un caso IEEE o un trabajo propio con resultado conocido.
3. **Una capa por vez**, empezando por lo que se esté cursando, para que cada
   avance se pueda contrastar con la clase.

## Estado actual

| Hecho | Detalle |
|---|---|
| Flujo de cargas | pandapower y OpenDSS, validados contra `ejemplo_4_barras` |
| Cortocircuito IEC 60909: 3F, 2F, 1F | pandapower (`--cortocircuito --fallas 1f,2f`); ATP además 2FT |
| ATPDraw dibujado desde `red.yaml` | adaptador `atpdraw`: flujo (con Dyn5 y capacitancia) y falla trifásica, validado contra `ejemplo_4_barras` y `subestacion_75kva` |
| Informe Word, verificación NTC/RETIE | `power-studies informe`, `power-studies verificar` |

## Pasos

| # | Paso | Qué se agrega | Herramienta | Validación | Estado |
|---|---|---|---|---|---|
| 1 | Cerrar ATPDraw | desfase de grupos Dyn, capacitancia de líneas, equivalente de Thevenin para cortocircuito | ATPDraw/ATP | `subestacion_75kva` contra pandapower | ✅ |
| 2 | Cortocircuitos asimétricos | fallas 1F, 2F y 2FT; datos de secuencia cero en red, líneas y transformadores | pandapower (1F, 2F), ATP (1F, 2F, 2FT) | componentes simétricas a mano sobre `subestacion_75kva` (`tests/test_fallas.py`) | ✅ |
| 3 | Protecciones | relés con curvas IEC/IEEE, fusibles, TC/TP; tiempos de disparo y coordinación | pandapower + cálculo propio, ATP | `informe_coordinacion.pdf` del 75 kVA | ⬜ |
| 4 | Generadores en el modelo | barras PV, límites de P/Q, costos | todas | — (habilita 5 y 8) | ⬜ |
| 5 | Análisis de Sistemas de Potencia | despacho económico, OPF, flujo DC/PTDF, estimación de estados, AGC | pandapower, MATPOWER | IEEE 14 barras en MATPOWER | ⬜ |
| 6 | Distribución desbalanceada | redes mono/bifásicas, perfiles horarios, QSTS, pérdidas, armónicos | OpenDSS | IEEE 13 nodos | ⬜ |
| 7 | Transmisión y transitorios | líneas por geometría (LCC), rayos, sobretensiones, malla de puesta a tierra | ATP | proyecto de malla de alta frecuencia (2026-1) | ⬜ |
| 8 | Generación y estabilidad | máquina síncrona, excitación, gobernador, FV y eólica; estabilidad transitoria | PowerFactory, ATP | caso de 9 barras de Anderson | ⬜ |

Estados: ⬜ pendiente · 🟨 en curso · ✅ validado.

## Por qué este orden

- **1** deja ATPDraw usable en el caso real (el 75 kVA es Dyn5).
- **2 → 3**: la coordinación de protecciones necesita las corrientes de falla asimétricas.
- **4 → 5 y 8**: despacho, OPF y estabilidad necesitan generadores en el modelo.
- **6** reutiliza el adaptador de OpenDSS ya existente.
- **7 y 8** son los más complejos: se dejan para cuando el modelo esté maduro.
