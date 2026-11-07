# Una base de Supabase "de mentira", en memoria, para los tests.
#
# Imita la parte del cliente de Supabase que usa src/base_de_datos.py:
#   cliente.table("partidas").select("...").eq(...).in_(...).is_(...).order(...)
#          .range(desde, hasta).execute().data
#   cliente.table("x").upsert(filas, on_conflict="a,b").execute()
#   cliente.rpc("guardar_partida", {...}).execute()
# y respeta las mismas reglas que las tablas de supabase/esquema.sql que nos
# importan: claves únicas, y guardar_partida que no duplica.
# Con .fallar = True cada pedido lanza un error, como si no hubiera internet.

import copy
import uuid

CLAVES_UNICAS = {
    "jugadores": ("clave",),
    "partidas": ("jugador_id", "clave"),
    "jugadas": ("partida_id", "indice"),
    "evaluaciones": ("posicion",),
}


class Respuesta:
    def __init__(self, data):
        self.data = data


class SupabaseFalso:
    def __init__(self):
        self.tablas = {nombre: [] for nombre in CLAVES_UNICAS}
        self.fallar = False
        self.pedidos = 0   # cuántos pedidos se hicieron (para ver que se usa la caché)

    def table(self, nombre):
        return Consulta(self, nombre)

    def rpc(self, nombre, parametros):
        return LlamadaRpc(self, nombre, parametros)

    def _pedido(self):
        self.pedidos += 1
        if self.fallar:
            raise ConnectionError("Sin conexión (simulado)")


class LlamadaRpc:
    def __init__(self, base, nombre, parametros):
        self.base, self.nombre, self.parametros = base, nombre, parametros

    def execute(self):
        self.base._pedido()
        assert self.nombre == "guardar_partida"
        jugador = self.parametros["p_jugador"]
        partida = copy.deepcopy(self.parametros["p_partida"])
        # Como jsonb_populate_record: los enteros tienen que venir como enteros.
        for clave in ("cantidad_jugadas", "jugada_enroque", "menores_desarrolladas"):
            assert partida.get(clave) is None or isinstance(partida[clave], int), clave
        partidas = self.base.tablas["partidas"]
        if any(p["jugador_id"] == jugador and p["clave"] == partida["clave"] for p in partidas):
            return Respuesta(None)          # ya estaba: no hace nada
        nuevo_id = str(uuid.uuid4())
        partidas.append({**partida, "id": nuevo_id, "jugador_id": jugador})
        for jugada in self.parametros["p_jugadas"]:
            self.base.tablas["jugadas"].append({**copy.deepcopy(jugada), "partida_id": nuevo_id})
        return Respuesta(nuevo_id)


class Consulta:
    def __init__(self, base, tabla):
        self.base, self.tabla = base, tabla
        self.columnas = None
        self.filtros = []
        self.orden = []
        self.rango = None
        self.escritura = None   # ("upsert", filas, on_conflict)

    # --- lectura
    def select(self, columnas="*"):
        self.columnas = None if columnas == "*" else [c.strip() for c in columnas.split(",")]
        return self

    def eq(self, columna, valor):
        self.filtros.append(lambda fila: fila.get(columna) == valor)
        return self

    def in_(self, columna, valores):
        valores = set(valores)
        self.filtros.append(lambda fila: fila.get(columna) in valores)
        return self

    def is_(self, columna, valor):
        assert valor == "null"
        self.filtros.append(lambda fila: fila.get(columna) is None)
        return self

    def order(self, columna, desc=False):
        self.orden.append((columna, desc))
        return self

    def range(self, desde, hasta):
        self.rango = (desde, hasta)
        return self

    # --- escritura
    def upsert(self, filas, on_conflict="", ignore_duplicates=False):
        filas = filas if isinstance(filas, list) else [filas]
        self.escritura = ("upsert", copy.deepcopy(filas), on_conflict, ignore_duplicates)
        return self

    def execute(self):
        self.base._pedido()
        tabla = self.base.tablas[self.tabla]
        if self.escritura is not None:
            return Respuesta(self._upsert(tabla))
        filas = [fila for fila in tabla if all(f(fila) for f in self.filtros)]
        for columna, desc in reversed(self.orden):
            filas.sort(key=lambda fila: (fila.get(columna) is None, fila.get(columna)), reverse=desc)
        if self.rango is not None:
            filas = filas[self.rango[0]:self.rango[1] + 1]
        if self.columnas is not None:
            filas = [{c: fila.get(c) for c in self.columnas} for fila in filas]
        return Respuesta(copy.deepcopy(filas))

    def _upsert(self, tabla):
        _, filas, on_conflict, ignorar = self.escritura
        claves = tuple(c.strip() for c in on_conflict.split(",")) if on_conflict \
            else CLAVES_UNICAS[self.tabla]
        assert claves == CLAVES_UNICAS[self.tabla], "on_conflict tiene que ser la clave única"
        resultado = []
        for fila in filas:
            existente = next((f for f in tabla if all(f.get(c) == fila.get(c) for c in claves)), None)
            if existente is None:
                nueva = dict(fila)
                if self.tabla in ("jugadores", "partidas"):
                    nueva.setdefault("id", str(uuid.uuid4()))
                tabla.append(nueva)
                resultado.append(copy.deepcopy(nueva))
            elif not ignorar:
                existente.update(fila)
                resultado.append(copy.deepcopy(existente))
        return resultado
