# Guía PowerFactory

Hay dos direcciones: **traer** un proyecto existente al modelo neutro y
**llevar** el modelo neutro a PowerFactory (red + unifilar + simulación).

## 1. Traer un proyecto existente (p. ej. `subestaciones 75 kva`)

El `.pfd` es binario y solo PowerFactory lo lee.

1. En PowerFactory active el proyecto y su caso de estudio.
2. Cree un *Python Script* (ComPython) que apunte a
   `herramientas/powerfactory/pf_exportar_modelo.py` y ejecútelo.
3. Se escribe `Documentos\modelo_neutro_75kva.json`: red, tipos, posiciones del
   unifilar y resultados del flujo de cargas.
4. Conviértalo: `power-studies importar-pf modelo_neutro_75kva.json --salida modelo/red.yaml`.
   Los resultados de PowerFactory quedan como `referencia`, así que cada
   simulación posterior se compara sola contra PowerFactory.

## 2. Llevar el modelo a PowerFactory

```bash
power-studies exportar modelo/red.yaml --herramienta powerfactory --salida pf/
```

Copie `pf/` al Windows con PowerFactory y elija:

**Con interfaz:** active el proyecto destino, cree un ComPython apuntando a
`pf_construir_red.py`, ajuste `MODELO_JSON` y ejecútelo.

**Sin interfaz (modo motor), ideal para agentes:**

```bat
set PF_PYTHON=C:\Program Files\DIgSILENT\PowerFactory 2024\Python\3.12
python pf_motor.py --proyecto "mi proyecto" --modelo modelo.json
```

El script:
1. Crea la red `PS_<proyecto>` con barras, cables, transformadores (tipos en
   `Librería de equipos/power_studies`), cargas, FV y red externa.
2. Dibuja el unifilar: primero intenta el diagramado automático de PowerFactory;
   si no existe en su versión, coloca los símbolos en las posiciones del modelo.
3. Corre flujo de cargas (AC balanceado, sin ajuste automático de taps) y
   cortocircuito IEC 60909.
4. Escribe `resultados_powerfactory.json` en el formato común.

## 3. Si algo falla

Los scripts están escritos contra la API documentada y probados con una API
simulada (`tests/fake_powerfactory.py`), pero **aún no con una licencia real**.
Errores típicos y qué hacer:

| Síntoma | Causa probable | Solución |
|---|---|---|
| `AttributeError` en un atributo (`tr2cn_h`, `nt2ag`, ...) | nombre distinto en su versión | copie el error; se ajusta en `pf_construir_red.py` |
| Símbolos aparecen sin conexiones | nombres de símbolo distintos | corra `pf_exportar_modelo.py` sobre un diagrama suyo y copie los valores `simbolo` a `SIMBOLOS` |
| No dibuja nada | sin auto-diagramado y sin símbolos válidos | la red queda creada y simulada; use *Dibujar elementos de red existentes* |
| `GetApplicationExt` falla | licencia sin Python externo o versión de Python distinta | use la opción con interfaz |

Envíe el texto de la ventana de salida y la versión de PowerFactory para corregirlo.
