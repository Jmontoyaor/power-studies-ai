@AGENTS.md

## Notas para Claude Code

- Los subagentes viven en `.claude/agents/` y los comandos en `.claude/commands/`
  (`/estudio`, `/estudio-nuevo`, `/estudio-continuar`).
- Tú eres el coordinador: despachas a los subagentes fase por fase, actualizas
  `estudios/<id>/ESTADO.md` y te detienes en cada gate.
- Si la sesión está vinculada al computador Windows del usuario y tiene
  PowerFactory, la Fase 4 puede correr `herramientas/powerfactory/pf_motor.py`
  allí directamente; si no, entrega la carpeta exportada y espera el
  `resultados_powerfactory.json`.
