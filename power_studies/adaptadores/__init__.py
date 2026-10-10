"""Registro de adaptadores. Para sumar una herramienta: escriba la clase y
agréguela a REGISTRO."""
from .atpdraw_ad import ATPDrawAdaptador
from .base import Adaptador
from .opendss_ad import OpenDSSAdaptador
from .pandapower_ad import PandapowerAdaptador
from .plantillas_ad import ATPAdaptador, ETAPAdaptador, PVsystAdaptador
from .powerfactory_ad import PowerFactoryAdaptador

REGISTRO: dict[str, type[Adaptador]] = {
    a.nombre: a for a in (PandapowerAdaptador, OpenDSSAdaptador, PowerFactoryAdaptador,
                          ATPAdaptador, ATPDrawAdaptador, ETAPAdaptador, PVsystAdaptador)
}


def obtener(nombre: str) -> Adaptador:
    try:
        return REGISTRO[nombre]()
    except KeyError:
        raise KeyError(f"herramienta '{nombre}' no registrada; opciones: {sorted(REGISTRO)}") from None
