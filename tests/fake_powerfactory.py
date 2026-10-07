"""Imitación mínima de la API de PowerFactory para probar los scripts
pf_construir_red.py y pf_exportar_modelo.py sin licencia.

Solo reproduce el comportamiento estructural (crear objetos, contenidos,
atributos, cubículos); no calcula nada eléctrico. Sirve para detectar
errores de lógica y de nombres de campos propios antes de ir a la máquina
con PowerFactory.
"""


class Obj:
    def __init__(self, clase, nombre, padre=None):
        object.__setattr__(self, "_attrs", {})
        object.__setattr__(self, "_hijos", [])
        object.__setattr__(self, "_clase", clase)
        object.__setattr__(self, "loc_name", nombre)
        object.__setattr__(self, "_padre", padre)

    # --- API usada por los scripts ---
    def CreateObject(self, clase, nombre):
        o = Obj(clase, nombre, self)
        self._hijos.append(o)
        return o

    def GetContents(self, patron="*", recursivo=0):
        nombre, _, clase = patron.rpartition(".")
        out = []
        for h in self._hijos:
            if (clase in ("*", h._clase)) and (nombre in ("*", "", h.loc_name)):
                out.append(h)
            if recursivo:
                out += h.GetContents(patron, 1)
        return out

    def GetClassName(self):
        return self._clase

    def GetAttribute(self, nombre):
        if nombre.startswith(("m:", "c:")):
            return self._attrs.get(nombre, 0.0)
        if nombre in self._attrs:
            return self._attrs[nombre]
        raise AttributeError(nombre)

    def HasAttribute(self, nombre):
        return True

    def Activate(self):
        return 0

    def Execute(self):
        return 0

    @property
    def cterm(self):
        return self._padre if self._clase == "StaCubic" else None

    def __getattr__(self, nombre):
        try:
            return self._attrs[nombre]
        except KeyError:
            raise AttributeError(nombre) from None

    def __setattr__(self, nombre, valor):
        if nombre == "loc_name":
            object.__setattr__(self, nombre, valor)
        else:
            self._attrs[nombre] = valor

    def __repr__(self):
        return f"<{self.loc_name}.{self._clase}>"


class App:
    def __init__(self, con_layout=False):
        self.proyecto = Obj("IntPrj", "proyecto_prueba")
        self.carpetas = {k: self.proyecto.CreateObject("IntPrjfolder", k)
                         for k in ("netdat", "equip", "dia", "study")}
        self.caso = self.proyecto.CreateObject("IntCase", "caso")
        self.con_layout = con_layout
        self.salida = []

    def GetActiveProject(self):
        return self.proyecto

    def GetActiveStudyCase(self):
        return self.caso

    def GetProjectFolder(self, k):
        return self.carpetas[k]

    def GetFromStudyCase(self, clase):
        if clase == "ComSgllayout" and not self.con_layout:
            return None
        existentes = self.caso.GetContents("*." + clase)
        return existentes[0] if existentes else self.caso.CreateObject(clase, clase)

    def GetCalcRelevantObjects(self, patron):
        return self.carpetas["netdat"].GetContents(patron, 1)

    def PrintPlain(self, msg):
        self.salida.append(msg)

    def ClearOutputWindow(self):
        pass
