"""Dimensionamiento de bancos de baterías plomo-ácido según IEEE Std 485-2020 (cláusula 6).

Cada función cita la cláusula o ecuación de la norma. Se valida contra el ejemplo de
la Figura A.1 del Anexo A (`tests/test_baterias.py`).

Datos que entrega el fabricante: el factor de capacidad Kt (Ah nominales / A que da la
celda durante t min hasta la tensión mínima) o Rt (A por placa positiva durante t min),
en función de t. Aquí se dan como tabla (t en min -> factor) y se interpola linealmente
entre puntos; la norma los lee de la curva del fabricante, así que conviene dar los
tiempos exactos que pide el ciclo (columna 5 de la planilla).

El cargador se dimensiona con IEEE Std 946-2020, 7.3 y Anexo B (`cargador`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Tabla 1 de IEEE 485-2020: factor de corrección por temperatura (°C -> factor),
# celdas plomo-ácido de densidad 1,215 con capacidad nominal a 25 °C.
TABLA_TEMPERATURA = [
    (4.4, 1.300), (7.2, 1.250), (10.0, 1.190), (12.8, 1.150), (15.6, 1.110), (18.3, 1.080),
    (18.9, 1.072), (19.4, 1.064), (20.0, 1.056), (20.6, 1.048), (21.1, 1.040), (21.7, 1.034),
    (22.2, 1.029), (22.8, 1.023), (23.4, 1.017), (23.9, 1.011), (24.5, 1.006), (25.0, 1.000),
    (25.6, 0.994), (26.1, 0.987), (26.7, 0.980), (27.2, 0.976), (27.8, 0.972), (28.3, 0.968),
    (28.9, 0.964), (29.4, 0.960), (30.0, 0.956), (30.6, 0.952), (31.1, 0.948), (31.6, 0.944),
    (32.2, 0.940), (35.0, 0.930), (37.8, 0.910), (40.6, 0.890), (43.3, 0.880), (46.1, 0.870),
    (48.9, 0.860),
]


@dataclass
class Periodo:
    amperios: float
    minutos: float


@dataclass
class Resultado:
    secciones: dict[int, float]        # sección S -> F_S (las omitidas por la regla de 6.4.2 no aparecen)
    seccion_maxima: int
    tamano_ciclo: float                # máx F_S, ec. (2)
    tamano_aleatorio: float            # 6.4.4
    sin_corregir: float                # líneas (10)-(11) de la planilla
    factor_temperatura: float
    margen: float
    envejecimiento: float
    corregido: float                   # línea (15)
    unidad: str                        # "Ah" (con Kt) o "placas positivas" (con Rt)
    notas: list[str] = field(default_factory=list)


def numero_celdas(v_max_sistema: float, v_igualacion_celda: float) -> tuple[int, float]:
    """6.2.2: número de celdas = tensión máxima del sistema / tensión de igualación por celda,
    redondeado como en los ejemplos de la norma (60,09 -> 60; 57,94 -> 58).

    Devuelve (celdas, tensión de igualación resultante). Si se redondeó hacia arriba, esa
    tensión supera la máxima del sistema y la norma pide verificar la carga."""
    n = round(v_max_sistema / v_igualacion_celda)
    return n, n * v_igualacion_celda


def tension_minima_celda(v_min_bateria: float, n_celdas: int) -> float:
    """6.2.2: tensión mínima por celda = tensión mínima de batería / número de celdas."""
    return v_min_bateria / n_celdas


def factor_temperatura(t_c: float) -> float:
    """6.3.2 y Tabla 1: interpola y redondea a dos decimales como indica la norma;
    los valores tabulados se usan tal cual."""
    if t_c >= 25.0:
        return 1.0  # 6.3.2: sobre la temperatura nominal, no se reduce el tamaño (práctica conservadora)
    for t, f in TABLA_TEMPERATURA:
        if math.isclose(t, t_c, abs_tol=0.05):
            return f
    if t_c < TABLA_TEMPERATURA[0][0]:
        raise ValueError(f"{t_c} °C fuera de la Tabla 1: consulte al fabricante")
    for (t1, f1), (t2, f2) in zip(TABLA_TEMPERATURA, TABLA_TEMPERATURA[1:]):
        if t1 <= t_c <= t2:
            return round(f1 + (f2 - f1) * (t_c - t1) / (t2 - t1), 2)
    raise AssertionError("inalcanzable")


def _factor(tabla: dict[float, float], t: float, interpolados: set[float] | None = None) -> float:
    if t in tabla:
        return tabla[t]
    if interpolados is not None:
        interpolados.add(t)
    puntos = sorted(tabla.items())
    if not puntos[0][0] <= t <= puntos[-1][0]:
        raise ValueError(f"t = {t} min fuera de la tabla del fabricante ({puntos[0][0]}-{puntos[-1][0]} min)")
    for (t1, k1), (t2, k2) in zip(puntos, puntos[1:]):
        if t1 <= t <= t2:
            return k1 + (k2 - k1) * (t - t1) / (t2 - t1)
    raise AssertionError("inalcanzable")


def dimensionar(ciclo: list[Periodo], factores: dict[float, float], tipo_factor: str = "kt",
                aleatoria: Periodo | None = None, temperatura_c: float = 25.0,
                margen: float = 1.10, envejecimiento: float = 1.25) -> Resultado:
    """6.4: tamaño de celda para un ciclo de trabajo.

    F_S = Σ_{P=1..S} (A_P − A_{P−1})·Kt   [ec. (4)]  o  (A_P − A_{P−1}) / Rt  [ec. (3)],
    con t = minutos desde el inicio del periodo P hasta el fin de la sección S.
    Si A_{S+1} > A_S, la sección S se omite (6.4.2)."""
    if tipo_factor not in ("kt", "rt"):
        raise ValueError("tipo_factor debe ser 'kt' (Ah) o 'rt' (placas positivas)")
    aplicar = (lambda da, f: da * f) if tipo_factor == "kt" else (lambda da, f: da / f)
    secciones: dict[int, float] = {}
    notas = []
    interpolados: set[float] = set()
    for s in range(1, len(ciclo) + 1):
        if s < len(ciclo) and ciclo[s].amperios > ciclo[s - 1].amperios:
            continue  # la sección S+1 exige más: se omite S (6.4.2)
        fs, anterior = 0.0, 0.0
        for p in range(s):
            t = sum(per.minutos for per in ciclo[p:s])
            fs += aplicar(ciclo[p].amperios - anterior, _factor(factores, t, interpolados))
            anterior = ciclo[p].amperios
        secciones[s] = fs
    s_max = max(secciones, key=secciones.get)
    tam_aleatorio = (aplicar(aleatoria.amperios, _factor(factores, aleatoria.minutos, interpolados))
                     if aleatoria else 0.0)
    sin_corregir = secciones[s_max] + tam_aleatorio
    ft = factor_temperatura(temperatura_c)
    if not 1.10 <= margen <= 1.15:
        notas.append("6.3.3 sugiere un margen de diseño de 10 % a 15 %.")
    if envejecimiento < 1.25:
        notas.append("6.3.4: con factor de envejecimiento < 1,25 verifique la capacidad inicial (6.3.5).")
    if interpolados:
        notas.append("Factores interpolados linealmente para t = "
                     + ", ".join(f"{x:g}" for x in sorted(interpolados))
                     + " min: confirme esos valores en la curva del fabricante.")
    corregido = sin_corregir * ft * margen * envejecimiento
    return Resultado(secciones=secciones, seccion_maxima=s_max, tamano_ciclo=secciones[s_max],
                     tamano_aleatorio=tam_aleatorio, sin_corregir=sin_corregir, factor_temperatura=ft,
                     margen=margen, envejecimiento=envejecimiento, corregido=corregido,
                     unidad="Ah" if tipo_factor == "kt" else "placas positivas", notas=notas)


def celda_comercial(requerido: float, disponibles: list[float]) -> float | None:
    """6.3.3 y planilla línea (16): la siguiente celda comercial mayor o igual."""
    mayores = [c for c in sorted(disponibles) if c >= requerido - 1e-9]
    return mayores[0] if mayores else None


# IEEE 946-2020, Tabla 1: factor de eficiencia de recarga e por tipo de batería.
FACTOR_RECARGA = {"VLA": 1.1, "VRLA": 1.15, "NiCd_ventilada": 1.3, "NiCd_recombinante": 1.14}


@dataclass
class ResultadoCargador:
    ic: float          # ec. (1): recarga + carga continua
    i2: float          # ec. (2): carga continua + no continua (con K, como en el Anexo B)
    i3: float          # ec. (3): salida nominal mínima = máx(Ic, I2)
    k: float
    e: float
    comercial: float | None = None


def ah_extraidos(ciclo: list[Periodo], aleatoria: Periodo | None = None) -> float:
    """Ah que el ciclo de trabajo extrae de la batería (C de IEEE 946, 7.3.1)."""
    total = sum(p.amperios * p.minutos for p in ciclo) + (aleatoria.amperios * aleatoria.minutos if aleatoria else 0)
    return total / 60


def cargador(c_ah: float, t_recarga_h: float, i_continua: float, tipo_bateria: str = "VLA",
             factores_k: list[float] | None = None, i_no_continua: float = 0.0,
             comerciales: list[float] | None = None) -> ResultadoCargador:
    """IEEE 946-2020, 7.3: Ic = K·(C·e/t + I_L) [ec. (1)], I2 = K·(I_L + I_LN) [ec. (2), Anexo B]
    e I3 = máx(Ic, I2) [ec. (3)]. K es el producto de los factores (altitud, crecimiento, ...)."""
    if not 6 <= t_recarga_h <= 24:
        raise ValueError("7.3.1: el tiempo de recarga suele estar entre 6 h y 24 h")
    e = FACTOR_RECARGA[tipo_bateria]
    k = math.prod(factores_k or [1.0])
    ic = k * (c_ah * e / t_recarga_h + i_continua)
    i2 = k * (i_continua + i_no_continua)
    i3 = max(ic, i2)
    return ResultadoCargador(ic=ic, i2=i2, i3=i3, k=k, e=e,
                             comercial=celda_comercial(i3, comerciales) if comerciales else None)
