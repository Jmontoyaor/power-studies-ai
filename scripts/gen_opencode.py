#!/usr/bin/env python3
"""Genera la versión OpenCode (.opencode/) de los agentes y comandos de
Claude Code (.claude/), que son la única fuente editada a mano.

    python scripts/gen_opencode.py                 # modelo heredado de su config de OpenCode
    python scripts/gen_opencode.py --modelos scripts/modelos_opencode.json

modelos_opencode.json: {"opus": "proveedor/modelo-fuerte", "sonnet": "proveedor/modelo-rapido"}
o por agente: {"redactor-informe": "openai/gpt-5.4", ...}
"""
import argparse
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def partir(texto):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", texto, re.S)
    meta = {}
    for linea in m.group(1).splitlines():
        k, _, v = linea.partition(":")
        meta[k.strip()] = v.strip()
    return meta, m.group(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos")
    a = ap.parse_args()
    mapa = json.loads(Path(a.modelos).read_text()) if a.modelos else {}
    out_a = RAIZ / ".opencode" / "agent"
    out_c = RAIZ / ".opencode" / "command"
    out_a.mkdir(parents=True, exist_ok=True)
    out_c.mkdir(parents=True, exist_ok=True)
    for f in sorted((RAIZ / ".claude" / "agents").glob("*.md")):
        meta, cuerpo = partir(f.read_text(encoding="utf-8"))
        modelo = mapa.get(meta["name"]) or mapa.get(meta.get("model", ""))
        fm = [f"description: {meta['description']}", "mode: subagent"]
        if modelo:
            fm.append(f"model: {modelo}")
        (out_a / f.name).write_text("---\n" + "\n".join(fm) + "\n---\n" + cuerpo, encoding="utf-8")
    for f in sorted((RAIZ / ".claude" / "commands").glob("*.md")):
        meta, cuerpo = partir(f.read_text(encoding="utf-8"))
        cuerpo = cuerpo.replace("Despacha al subagente", "Delega (herramienta task) al subagente")
        (out_c / f.name).write_text(f"---\ndescription: {meta['description']}\n---\n" + cuerpo, encoding="utf-8")
    print(f"OpenCode: {len(list(out_a.glob('*.md')))} agentes, {len(list(out_c.glob('*.md')))} comandos")


if __name__ == "__main__":
    main()
