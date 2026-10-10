"""Modelo neutro de red eléctrica.

Es la única fuente de verdad del estudio. Los agentes leen y escriben este
modelo; los adaptadores (pandapower, OpenDSS, PowerFactory, ATP, ETAP,
PVsyst) lo traducen a cada herramienta y devuelven resultados en el formato
común de `resultados.py`.

Cada elemento lleva `origen`, que indica de dónde salió el dato:
    dato       -> tomado de planos, placas, fichas o del proyecto original
    deducido   -> calculado a partir de otros resultados
    supuesto   -> valor típico asumido; DEBE confirmarse antes de firmar
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Origen = Literal["dato", "deducido", "supuesto"]

# Constante de temperatura inferida (°C) para la corrección de resistencia
# R2/R1 = (T0 + T2)/(T0 + T1). Cobre 234,5; aluminio 228,1.
T0_MATERIAL = {"cu": 234.5, "al": 228.1}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    nombre: Optional[str] = None
    origen: Origen = "dato"
    nota: Optional[str] = None

    @property
    def etiqueta(self) -> str:
        return self.nombre or self.id


class Posicion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float


class Barra(_Base):
    un_kV: float = Field(gt=0, description="Tensión nominal de línea")
    pos: Optional[Posicion] = None


class RedExterna(_Base):
    barra: str
    u_pu: float = 1.0
    angulo_deg: float = 0.0
    scc_max_MVA: float = Field(100.0, gt=0)
    r_x_max: float = 0.1
    scc_min_MVA: Optional[float] = None
    r_x_min: Optional[float] = None
    x0_x1: Optional[float] = Field(None, gt=0, description="X0/X1 de la red (fallas a tierra)")
    r0_x0: Optional[float] = Field(None, ge=0, description="R0/X0 de la red (fallas a tierra)")


class Linea(_Base):
    desde: str
    hasta: str
    longitud_km: float = Field(gt=0)
    r_ohm_km: float = Field(ge=0)
    x_ohm_km: float = Field(ge=0)
    c_nF_km: float = 0.0
    in_kA: float = Field(gt=0, description="Corriente nominal / ampacidad")
    r0_ohm_km: Optional[float] = None
    x0_ohm_km: Optional[float] = None
    c0_nF_km: Optional[float] = Field(None, description="Capacitancia de secuencia cero (por defecto c_nF_km)")
    paralelos: int = 1
    tipo: Literal["cable", "aerea"] = "cable"
    material: Literal["cu", "al"] = "cu"
    temperatura_ref_C: float = Field(20.0, description="Temperatura a la que se da r_ohm_km")
    conductor: Optional[str] = Field(None, description="p. ej. '4/0 AWG Cu THHN'")

    def r_a(self, temperatura_C: float) -> float:
        """Resistencia (ohm/km) corregida a la temperatura de cálculo."""
        t0 = T0_MATERIAL[self.material]
        return self.r_ohm_km * (t0 + temperatura_C) / (t0 + self.temperatura_ref_C)


class Transformador(_Base):
    barra_at: str
    barra_bt: str
    sn_MVA: float = Field(gt=0)
    un_at_kV: float = Field(gt=0)
    un_bt_kV: float = Field(gt=0)
    uk_pct: float = Field(gt=0)
    pcu_kW: float = Field(ge=0, description="Pérdidas en el cobre a plena carga")
    p0_kW: float = 0.0
    i0_pct: float = 0.0
    uk0_pct: Optional[float] = Field(None, gt=0, description="Tensión de cc de secuencia cero (por defecto uk_pct)")
    ukr0_pct: Optional[float] = Field(None, ge=0, description="Parte resistiva de uk0 (por defecto ukr_pct)")
    grupo: str = Field("Dyn5", description="Grupo de conexión, p. ej. Dyn5, Yy0")
    tap_lado: Literal["at", "bt"] = "at"
    tap_paso_pct: float = 2.5
    tap_min: int = -2
    tap_max: int = 2
    tap_pos: int = 0

    @property
    def desfase_deg(self) -> float:
        digitos = "".join(c for c in self.grupo if c.isdigit())
        return 30.0 * int(digitos or 0)

    @property
    def ukr_pct(self) -> float:
        return self.pcu_kW / (self.sn_MVA * 1000.0) * 100.0


class Carga(_Base):
    barra: str
    p_MW: float
    q_Mvar: float = 0.0


class GeneradorPV(_Base):
    """Generación estática (FV, inversores). Se modela como PQ en flujo de cargas."""
    barra: str
    p_MW: float = Field(ge=0)
    q_Mvar: float = 0.0
    sn_MVA: float = Field(gt=0)
    k_cc: float = Field(1.2, description="Aporte a cortocircuito en múltiplos de In (inversor)")


class Proteccion(_Base):
    """Dispositivo de protección. Los ajustes son libres por tipo de dispositivo."""
    tipo: Literal["fusible", "rele", "reconectador", "interruptor"]
    ubicacion: str = Field(description="id del elemento o barra protegido")
    modelo: Optional[str] = None
    ajustes: dict = Field(default_factory=dict)


class Criterios(BaseModel):
    """Criterios de verificación (por defecto: práctica colombiana)."""
    model_config = ConfigDict(extra="forbid")
    u_min_pu: float = 0.90           # NTC 1340, -10 %
    u_max_pu: float = 1.05           # NTC 1340, +5 %
    caida_alimentador_pct: float = 3.0   # NTC 2050, nota informativa 215.2(A)
    caida_total_pct: float = 5.0         # NTC 2050, nota informativa 210.19(A)
    cargabilidad_max_pct: float = 100.0
    cargabilidad_alerta_pct: float = 80.0


class Escenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    descripcion: str = ""
    temperatura_C: float = 20.0
    escala_carga: float = 1.0
    taps: dict[str, int] = Field(default_factory=dict, description="id_trafo -> posición")


class Red(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proyecto: str
    descripcion: str = ""
    autor: Optional[str] = None
    frecuencia_Hz: float = 60.0
    barras: list[Barra]
    redes_externas: list[RedExterna]
    lineas: list[Linea] = Field(default_factory=list)
    transformadores: list[Transformador] = Field(default_factory=list)
    cargas: list[Carga] = Field(default_factory=list)
    generadores_pv: list[GeneradorPV] = Field(default_factory=list)
    protecciones: list[Proteccion] = Field(default_factory=list)
    criterios: Criterios = Field(default_factory=Criterios)
    escenarios: list[Escenario] = Field(default_factory=lambda: [Escenario(id="base")])
    referencia: Optional[dict] = Field(
        None, description="Resultados de referencia (p. ej. de PowerFactory) para validar adaptadores")

    # ---------- validación de integridad ----------
    @model_validator(mode="after")
    def _integridad(self):
        ids = [e.id for e in self.elementos()]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"ids repetidos: {sorted(dup)}")
        barras = {b.id for b in self.barras}

        def chk(ref, quien):
            if ref not in barras:
                raise ValueError(f"{quien}: la barra '{ref}' no existe")

        for x in self.redes_externas:
            chk(x.barra, x.id)
        for l in self.lineas:
            chk(l.desde, l.id); chk(l.hasta, l.id)
        for t in self.transformadores:
            chk(t.barra_at, t.id); chk(t.barra_bt, t.id)
            for lado, b in (("AT", t.barra_at), ("BT", t.barra_bt)):
                un = self.barra(b).un_kV
                nom = t.un_at_kV if lado == "AT" else t.un_bt_kV
                if abs(un - nom) / nom > 0.15:
                    raise ValueError(f"{t.id}: tensión {lado} {nom} kV no coincide con barra {b} ({un} kV)")
        for c in self.cargas + self.generadores_pv:
            chk(c.barra, c.id)
        if not self.redes_externas:
            raise ValueError("se necesita al menos una red externa (barra slack)")
        return self

    # ---------- utilidades ----------
    def elementos(self):
        return (self.barras + self.redes_externas + self.lineas + self.transformadores
                + self.cargas + self.generadores_pv + self.protecciones)

    def barra(self, id_: str) -> Barra:
        for b in self.barras:
            if b.id == id_:
                return b
        raise KeyError(id_)

    def escenario(self, id_: str | None = None) -> Escenario:
        if id_ is None:
            return self.escenarios[0]
        for e in self.escenarios:
            if e.id == id_:
                return e
        raise KeyError(f"escenario '{id_}' no existe")

    def ramas(self):
        """(id, barra_a, barra_b, objeto) para líneas y transformadores."""
        for l in self.lineas:
            yield l.id, l.desde, l.hasta, l
        for t in self.transformadores:
            yield t.id, t.barra_at, t.barra_bt, t

    def faltantes_secuencia_cero(self) -> list[str]:
        """Datos que faltan para calcular fallas a tierra (1F, 2FT). Vacío = completo."""
        out = [f"red externa {x.id}: x0_x1 y r0_x0" for x in self.redes_externas
               if x.x0_x1 is None or x.r0_x0 is None]
        out += [f"línea {l.id}: r0_ohm_km y x0_ohm_km" for l in self.lineas
                if l.r0_ohm_km is None or l.x0_ohm_km is None]
        return out

    def supuestos(self) -> list[str]:
        out = []
        for e in self.elementos():
            if e.origen != "dato":
                out.append(f"{e.etiqueta} [{e.origen}]" + (f": {e.nota}" if e.nota else ""))
        return out

    # ---------- E/S ----------
    @classmethod
    def cargar(cls, ruta: str | Path) -> "Red":
        ruta = Path(ruta)
        texto = ruta.read_text(encoding="utf-8")
        datos = json.loads(texto) if ruta.suffix == ".json" else yaml.safe_load(texto)
        return cls.model_validate(datos)

    def guardar(self, ruta: str | Path) -> None:
        ruta = Path(ruta)
        datos = self.model_dump(mode="json", exclude_none=True)
        if ruta.suffix == ".json":
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            ruta.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
