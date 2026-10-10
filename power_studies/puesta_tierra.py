"""Diseño de malla de puesta a tierra según IEEE Std 80-2013 (método simplificado, 16.4-16.5).

Cada función cita la ecuación de la norma. Se valida contra los ejemplos B.1, B.2 y
B.3 del Anexo B (`tests/test_puesta_tierra.py`).

Alcance (el mismo de las ecuaciones simplificadas de la norma): suelo uniforme,
malla rectangular de conductores paralelos equiespaciados, varillas opcionales.
Para suelo de dos capas o formas irregulares, IEEE 80 recomienda un programa de
cálculo (Anexo B, objetivo c).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Tabla 2 de IEEE 80-2013: constante Kf (Ta = 40 °C) por material y temperatura máxima.
KF = {
    "cu_recocido": 7.00,          # cobre recocido, 100 %, Tm = 1083 °C
    "cu_duro": 7.06,              # cobre duro comercial, 97 %, Tm = 1084 °C
    "cu_duro_250": 11.78,         # cobre duro comercial, 97 %, Tm = 250 °C (uniones mecánicas)
    "acero_cobrizado_40": 10.45,  # acero recubierto de cobre 40 %, Tm = 1084 °C
    "acero_cobrizado_30": 12.06,  # acero recubierto de cobre 30 %, Tm = 1084 °C
    "varilla_cobrizada_17": 14.64,
    "acero_aluminizado": 17.26,
    "acero_1020": 18.39,
    "varilla_inox": 14.72,
    "varilla_galvanizada": 28.96,
    "inox_304": 30.05,
}
KCMIL_A_MM2 = 0.5067


@dataclass
class Suelo:
    rho: float                     # resistividad del suelo, Ω·m
    rho_s: float | None = None     # resistividad de la capa superficial (gravilla), Ω·m
    h_s: float = 0.0               # espesor de la capa superficial, m


@dataclass
class Malla:
    lx: float                      # largo en x, m
    ly: float                      # largo en y, m
    nx: int                        # conductores paralelos al eje x (cada uno de largo lx)
    ny: int                        # conductores paralelos al eje y (cada uno de largo ly)
    h: float                       # profundidad de enterramiento, m
    d: float                       # diámetro del conductor, m
    n_varillas: int = 0
    l_varilla: float = 0.0         # largo de cada varilla, m
    varillas_en_perimetro: bool = True  # en esquinas/perímetro (Kii = 1 y LM de la ec. 91)

    @property
    def area(self) -> float:
        return self.lx * self.ly

    @property
    def lc(self) -> float:         # longitud total de conductor horizontal
        return self.nx * self.lx + self.ny * self.ly

    @property
    def lr(self) -> float:         # longitud total de varillas
        return self.n_varillas * self.l_varilla

    @property
    def lp(self) -> float:         # perímetro
        return 2 * (self.lx + self.ly)

    @property
    def espaciamiento(self) -> float:
        """D: separación entre conductores paralelos (promedio de ambas direcciones)."""
        dx = self.ly / (self.nx - 1)
        dy = self.lx / (self.ny - 1)
        return (dx + dy) / 2


@dataclass
class Falla:
    tres_i0: float                 # corriente simétrica de falla a tierra 3·I0, A
    sf: float = 1.0                # factor de división de corriente Sf (ec. 68)
    tf: float = 0.5                # duración de la falla, s
    ts: float | None = None        # duración del choque, s (por defecto = tf)
    x_r: float | None = None       # X/R en el punto de falla, para Df (ec. 84); None = Df 1
    tc: float | None = None        # duración para el calibre del conductor, s (por defecto = tf)
    i_calibre: float | None = None  # corriente para el calibre, A: la mayor falla a tierra, incluso las
                                    # de fuentes locales que no elevan el GPR (por defecto = tres_i0)


@dataclass
class Resultado:
    cs: float
    e_paso_tol: float
    e_toque_tol: float
    rg: float
    df: float
    ig: float
    gpr: float
    n: float
    km: float
    kii: float
    ki: float
    em: float
    ks: float
    es: float
    seccion_min_mm2: float
    cumple_toque: bool
    cumple_paso: bool
    notas: list[str] = field(default_factory=list)

    @property
    def cumple(self) -> bool:
        return self.cumple_toque and self.cumple_paso


def factor_cs(suelo: Suelo) -> float:
    """Ec. (27): factor de reducción por la capa superficial."""
    if not suelo.rho_s or suelo.h_s <= 0:
        return 1.0
    return 1 - 0.09 * (1 - suelo.rho / suelo.rho_s) / (2 * suelo.h_s + 0.09)


def tensiones_tolerables(suelo: Suelo, ts: float, peso_kg: int = 70) -> tuple[float, float]:
    """Ec. (29)-(30) y (32)-(33): (E_paso, E_toque) tolerables en V para 50 o 70 kg."""
    k = {50: 0.116, 70: 0.157}[peso_kg]
    rho_s = suelo.rho_s if suelo.rho_s and suelo.h_s > 0 else suelo.rho
    cs = factor_cs(suelo)
    return ((1000 + 6 * cs * rho_s) * k / math.sqrt(ts),
            (1000 + 1.5 * cs * rho_s) * k / math.sqrt(ts))


def resistencia_malla(suelo: Suelo, malla: Malla) -> float:
    """Ec. (57), Sverak: resistencia de la malla (con varillas en LT)."""
    lt = malla.lc + malla.lr
    a = malla.area
    return suelo.rho * (1 / lt + 1 / math.sqrt(20 * a) * (1 + 1 / (1 + malla.h * math.sqrt(20 / a))))


def factor_decremento(tf: float, x_r: float | None, f_hz: float = 60.0) -> float:
    """Ec. (84): Df = sqrt(1 + Ta/tf·(1 - e^(-2tf/Ta))), con Ta = X/(ωR)."""
    if not x_r:
        return 1.0
    ta = x_r / (2 * math.pi * f_hz)
    return math.sqrt(1 + ta / tf * (1 - math.exp(-2 * tf / ta)))


def n_efectivo(malla: Malla) -> float:
    """Ec. (89)-(93): número efectivo de conductores paralelos n = na·nb·nc·nd."""
    na = 2 * malla.lc / malla.lp
    cuadrada = math.isclose(malla.lx, malla.ly)
    nb = 1.0 if cuadrada else math.sqrt(malla.lp / (4 * math.sqrt(malla.area)))
    # nc = nd = 1 para mallas cuadradas y rectangulares (únicas soportadas aquí).
    return na * nb


def calibre_minimo(i_a: float, tc: float, material: str = "cu_duro") -> float:
    """Ec. (47): sección mínima en mm² (A_kcmil = I[kA]·Kf·√tc)."""
    return i_a / 1000 * KF[material] * math.sqrt(tc) * KCMIL_A_MM2


def disenar(suelo: Suelo, malla: Malla, falla: Falla, peso_kg: int = 70,
            material: str = "cu_duro", f_hz: float = 60.0) -> Resultado:
    """Procedimiento de 16.4 (pasos 2 a 10) y comparación con lo tolerable."""
    ts = falla.ts or falla.tf
    cs = factor_cs(suelo)
    e_paso, e_toque = tensiones_tolerables(suelo, ts, peso_kg)
    rg = resistencia_malla(suelo, malla)
    df = factor_decremento(falla.tf, falla.x_r, f_hz)
    ig = df * falla.sf * falla.tres_i0                          # ec. (68)-(69)
    gpr = ig * rg
    n = n_efectivo(malla)
    d, h, dd = malla.espaciamiento, malla.h, malla.d
    con_varillas = malla.n_varillas > 0 and malla.varillas_en_perimetro
    kii = 1.0 if con_varillas else 1 / (2 * n) ** (2 / n)       # ec. (87)
    kh = math.sqrt(1 + h / 1.0)                                 # ec. (88), h0 = 1 m
    km = 1 / (2 * math.pi) * (math.log(d ** 2 / (16 * h * dd) + (d + 2 * h) ** 2 / (8 * d * dd) - h / (4 * dd))
                              + kii / kh * math.log(8 / (math.pi * (2 * n - 1))))   # ec. (86)
    ki = 0.644 + 0.148 * n                                      # ec. (94)
    if con_varillas:                                            # ec. (96)
        lm = malla.lc + (1.55 + 1.22 * malla.l_varilla / math.hypot(malla.lx, malla.ly)) * malla.lr
    else:                                                       # ec. (95)
        lm = malla.lc + malla.lr
    em = suelo.rho * km * ki * ig / lm                          # ec. (85)
    ks = 1 / math.pi * (1 / (2 * h) + 1 / (d + h) + 1 / d * (1 - 0.5 ** (n - 2)))  # ec. (99)
    ls = 0.75 * malla.lc + 0.85 * malla.lr                      # ec. (98)
    es = suelo.rho * ks * ki * ig / ls                          # ec. (97)
    seccion = calibre_minimo((falla.i_calibre or falla.tres_i0) * df, falla.tc or falla.tf, material)
    notas = []
    if gpr <= e_toque:
        notas.append("GPR menor que la tensión de toque tolerable: el diseño es seguro sin más cálculo (paso 7).")
    if not 0.25 <= h <= 2.5:
        notas.append("h fuera de 0,25-2,5 m: fuera del rango de validez de las ecuaciones simplificadas.")
    if not (malla.d < 0.25 * h and d > 2.5):
        notas.append("Revisar validez: se requiere d < 0,25·h y D > 2,5 m (16.5.1).")
    return Resultado(cs=cs, e_paso_tol=e_paso, e_toque_tol=e_toque, rg=rg, df=df, ig=ig, gpr=gpr,
                     n=n, km=km, kii=kii, ki=ki, em=em, ks=ks, es=es, seccion_min_mm2=seccion,
                     cumple_toque=em <= e_toque, cumple_paso=es <= e_paso, notas=notas)
