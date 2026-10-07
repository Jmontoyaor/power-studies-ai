---
description: Ejecuta el pipeline completo de un estudio eléctrico, fase por fase, con puertas de aprobación
argument-hint: <id-del-estudio>
---

Eres el coordinador del estudio `estudios/$ARGUMENTS`. Sigue `AGENTS.md`.

Para cada fase:
1. Lee `ESTADO.md` y salta las fases ya aprobadas.
2. Despacha al subagente de la fase con un encargo autocontenido: ruta del estudio, qué entregar y dónde, y las notas de los gates anteriores.
3. Revisa la entrega (archivos existen, CLI con código 0).
4. **Gate**: presenta al usuario (a) resumen de lo hecho, (b) hallazgos y riesgos, (c) supuestos nuevos, (d) qué se aprueba. **Detente y espera la respuesta.**
5. Con la aprobación, actualiza `ESTADO.md` (fase → aprobada, fecha, nota) y sigue.

Fases y subagentes:
- 0 Insumos → `lector-insumos`
- 1 Modelo → `modelador`
- 2 Simulación → `simulador`
- 3 Verificación → `analista-normativo`
- 4 Herramientas (solo si el alcance pide PowerFactory/ATP/ETAP/PVsyst) → `integrador-herramientas`
- 5 Informe → `redactor-informe`, luego `revisor` (si el revisor pide cambios, vuelve al redactor una vez y reporta)

Si una CLI devuelve código 2 (discrepancia), no avances: muestra la tabla y pregunta.
