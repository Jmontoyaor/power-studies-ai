"""Interfaz común de adaptadores.

Agregar una herramienta nueva = crear una subclase de `Adaptador` y
registrarla en `adaptadores/__init__.py`. Nada más del proyecto cambia.
"""
from __future__ import annotations

from abc import ABC
from pathlib import Path

from ..modelo import Red
from ..resultados import Resultados


class Adaptador(ABC):
    #: nombre corto usado en la CLI
    nombre: str = ""
    #: qué sabe hacer: "flujo", "cortocircuito", "exportar", "grafico"
    capacidades: tuple[str, ...] = ()
    #: True si corre en este equipo sin software comercial
    local: bool = True

    def disponible(self) -> tuple[bool, str]:
        """(¿se puede usar aquí?, motivo)."""
        return True, "ok"

    def flujo(self, red: Red, escenario: str | None = None) -> Resultados:
        raise NotImplementedError(f"{self.nombre} no soporta flujo de cargas")

    def cortocircuito(self, red: Red, escenario: str | None = None) -> Resultados:
        raise NotImplementedError(f"{self.nombre} no soporta cortocircuito")

    def exportar(self, red: Red, carpeta: Path, escenario: str | None = None) -> list[Path]:
        """Escribe los archivos nativos de la herramienta (script, netlist, tablas)."""
        raise NotImplementedError(f"{self.nombre} no exporta archivos")
