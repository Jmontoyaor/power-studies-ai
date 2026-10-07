---
description: Crea la carpeta de un estudio eléctrico nuevo y la deja lista para recibir insumos
argument-hint: <id-del-estudio> [caso-base.yaml]
---

Crea un estudio nuevo con id `$ARGUMENTS` (primer argumento; el segundo, opcional, es un modelo base).

1. Corre `power-studies nuevo estudios/<id> [--desde <modelo base>]`.
2. Muestra al usuario la estructura creada y qué debe poner en `insumos/`:
   - planos/unifilares (PDF), fichas técnicas y placas;
   - si existe proyecto de PowerFactory: el JSON de `pf_exportar_modelo.py` (no el .pfd, que no se puede leer fuera de PowerFactory);
   - cuadro de cargas (Excel), datos del operador de red (Scc, X/R, tensión), términos de referencia.
3. Indica que el siguiente paso es `/estudio <id>` o `/estudio-continuar <id>`.
