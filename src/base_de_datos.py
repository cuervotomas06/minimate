# Conexión con Supabase (Postgres en la nube) para guardar y leer partidas.
#
# Este módulo solo habla con la base: lee y escribe filas. No sabe nada de
# ajedrez (eso está en src/datos.py y src/guardado.py).
#
# Credenciales: se leen de .streamlit/secrets.toml (st.secrets), con este formato:
#     [supabase]
#     url = "https://abcdefghijklmnop.supabase.co"
#     clave = "sb_secret_..."
# o de las variables de entorno SUPABASE_URL y SUPABASE_CLAVE (útil para los
# scripts). Si no hay credenciales, la app guarda en archivos locales (datos/).
#
# Las tablas se crean con supabase/esquema.sql (pegándolo en el SQL Editor).

import math
import os

TAMANO_PAGINA = 1000   # la API de Supabase devuelve como mucho 1000 filas por pedido
TAMANO_LOTE = 100      # cuántos valores mandamos juntos en un filtro "in" o un upsert
TIEMPO_MAXIMO = 15     # segundos de espera por pedido (si no hay internet, que no cuelgue)

# Columnas de la tabla partidas que leemos (todas menos el PGN, que pesa).
COLUMNAS_PARTIDAS = (
    "id,origen,clave,fecha,color,nivel,reloj,resultado,terminacion,cantidad_jugadas,"
    "eco,apertura,jugada_enroque,menores_desarrolladas,dama_temprana,mi_elo,elo_rival,link"
)


class ErrorBaseDeDatos(Exception):
    """Algo salió mal hablando con Supabase (sin internet, clave mal, etc.)."""


# ---------------------------------------------------------------------------
# Credenciales y cliente
# ---------------------------------------------------------------------------

_cliente_de_prueba = None   # los tests ponen acá una base simulada
_clientes = {}              # un cliente por (url, clave): se crea una sola vez


def usar_cliente_de_prueba(cliente):
    """Para los tests: usar una base simulada en vez de Supabase de verdad.
    Con None se vuelve al comportamiento normal."""
    global _cliente_de_prueba
    _cliente_de_prueba = cliente


def credenciales():
    """(url, clave) de Supabase, o None si no hay. Primero st.secrets, después
    las variables de entorno."""
    try:
        import streamlit as st
        seccion = st.secrets.get("supabase", {})
        url, clave = seccion.get("url"), seccion.get("clave")
        if url and clave:
            return url, clave
    except Exception:  # noqa: BLE001  (sin secrets.toml, st.secrets lanza un error)
        pass
    url, clave = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_CLAVE")
    if url and clave:
        return url, clave
    return None


def hay_supabase():
    """True si la app tiene que usar Supabase (si no, usa archivos locales)."""
    return _cliente_de_prueba is not None or credenciales() is not None


def cliente():
    """El cliente de Supabase (se crea la primera vez y después se reutiliza)."""
    if _cliente_de_prueba is not None:
        return _cliente_de_prueba
    datos = credenciales()
    if datos is None:
        raise ErrorBaseDeDatos("No hay credenciales de Supabase.")
    if datos not in _clientes:
        from supabase import ClientOptions, create_client
        _clientes[datos] = create_client(
            *datos, options=ClientOptions(postgrest_client_timeout=TIEMPO_MAXIMO))
    return _clientes[datos]


def ejecutar(consulta):
    """Ejecuta una consulta y devuelve las filas. Cualquier error (sin
    internet, tabla que no existe, permisos) se convierte en ErrorBaseDeDatos."""
    try:
        return consulta.execute().data
    except Exception as error:  # noqa: BLE001
        raise ErrorBaseDeDatos(resumir_error(error)) from error


def resumir_error(error):
    """Texto corto del error, para mostrarlo en la app (sin datos sensibles:
    los mensajes de Supabase no incluyen la clave)."""
    texto = str(error).strip().splitlines()[0] if str(error).strip() else ""
    return f"{type(error).__name__}: {texto[:160]}" if texto else type(error).__name__


def en_lotes(lista, tamano=TAMANO_LOTE):
    for inicio in range(0, len(lista), tamano):
        yield lista[inicio:inicio + tamano]


def todas_las_filas(armar_consulta):
    """Lee todas las filas de una consulta, de a páginas de 1000.
    armar_consulta() tiene que devolver una consulta nueva (con su orden)."""
    filas = []
    while True:
        pagina = ejecutar(armar_consulta().range(len(filas), len(filas) + TAMANO_PAGINA - 1))
        filas.extend(pagina)
        if len(pagina) < TAMANO_PAGINA:
            return filas


# ---------------------------------------------------------------------------
# Jugadores
# ---------------------------------------------------------------------------

def id_del_jugador(nombre, clave):
    """Id del jugador (lo crea si no existe). clave: el nombre normalizado."""
    filas = ejecutar(cliente().table("jugadores").upsert(
        {"nombre": nombre, "clave": clave}, on_conflict="clave"))
    return filas[0]["id"]


def buscar_jugador(clave):
    """Id del jugador con esa clave, o None (no lo crea)."""
    filas = ejecutar(cliente().table("jugadores").select("id").eq("clave", clave))
    return filas[0]["id"] if filas else None


def listar_jugadores():
    """Todos los jugadores (para el script de migración): id, nombre, clave."""
    return todas_las_filas(lambda: cliente().table("jugadores").select("id,nombre,clave")
                           .order("clave"))


def fusionar_jugadores(desde, hacia):
    """Pasa partidas y cuentas de un jugador a otro y borra el primero (ver
    fusionar_jugadores en migracion_01_cuentas.sql). Devuelve cuántas movió."""
    return ejecutar(cliente().rpc("fusionar_jugadores", {"p_desde": desde, "p_hacia": hacia}))


# ---------------------------------------------------------------------------
# Cuentas vinculadas (Google, Lichess, Chess.com)
# ---------------------------------------------------------------------------

def buscar_cuenta(proveedor, id_externo):
    """La fila de la cuenta, o None si nadie la vinculó."""
    filas = ejecutar(cliente().table("cuentas").select("*")
                     .eq("proveedor", proveedor).eq("id_externo", str(id_externo)))
    return filas[0] if filas else None


def crear_cuenta(jugador_id, proveedor, id_externo, usuario, verificado=True):
    """Vincula una cuenta externa a un jugador. Si la cuenta ya existía (de
    este u otro jugador) no la toca: devuelve la fila que quedó, para que
    quien llama vea de quién es."""
    ejecutar(cliente().table("cuentas").upsert(
        {"jugador_id": jugador_id, "proveedor": proveedor, "id_externo": str(id_externo),
         "usuario": usuario, "verificado": verificado},
        on_conflict="proveedor,id_externo", ignore_duplicates=True))
    return buscar_cuenta(proveedor, id_externo)


def cuentas_del_jugador(jugador_id):
    return ejecutar(cliente().table("cuentas").select("*").eq("jugador_id", jugador_id)
                    .order("proveedor"))


# ---------------------------------------------------------------------------
# Partidas y jugadas
# ---------------------------------------------------------------------------

def guardar_partida(jugador_id, partida, jugadas):
    """Guarda una partida con sus jugadas (todo junto, ver guardar_partida en
    esquema.sql). Devuelve True si era nueva y False si ya estaba."""
    resultado = ejecutar(cliente().rpc("guardar_partida", {
        "p_jugador": jugador_id, "p_partida": partida, "p_jugadas": jugadas}))
    return resultado is not None


def claves_guardadas(jugador_id, origen=None):
    """Las claves de las partidas que ya tiene el jugador (para no repetir)."""
    def consulta():
        armada = cliente().table("partidas").select("clave").eq("jugador_id", jugador_id)
        if origen is not None:
            armada = armada.eq("origen", origen)
        return armada.order("clave")
    return {fila["clave"] for fila in todas_las_filas(consulta)}


def leer_partidas(jugador_id):
    """Filas de la tabla partidas del jugador (sin el PGN)."""
    return todas_las_filas(lambda: cliente().table("partidas").select(COLUMNAS_PARTIDAS)
                           .eq("jugador_id", jugador_id).order("id"))


def leer_jugadas(ids_partidas):
    """Filas de la tabla jugadas de esas partidas."""
    filas = []
    for lote in en_lotes(list(ids_partidas), 50):
        filas.extend(todas_las_filas(
            lambda lote=lote: cliente().table("jugadas").select("*")
            .in_("partida_id", lote).order("partida_id").order("indice")))
    return filas


def partidas_sin_evaluar(jugador_id, origen="chesscom"):
    """[(id, pgn)] de las partidas del jugador con alguna jugada sin evaluación."""
    # 1) Las partidas de ese jugador y origen.
    todas = [fila["id"] for fila in todas_las_filas(
        lambda: cliente().table("partidas").select("id").eq("jugador_id", jugador_id)
        .eq("origen", origen).order("id"))]
    # 2) De esas, las que tienen alguna jugada con eval_despues vacía (null).
    ids = set()
    for lote in en_lotes(todas, 50):
        ids |= {fila["partida_id"] for fila in todas_las_filas(
            lambda lote=lote: cliente().table("jugadas").select("partida_id")
            .in_("partida_id", lote).is_("eval_despues", "null").order("partida_id"))}
    # 3) Su PGN, para volver a analizarlas.
    resultado = []
    for lote in en_lotes(sorted(ids), 50):
        resultado.extend((fila["id"], fila["pgn"]) for fila in ejecutar(
            cliente().table("partidas").select("id,pgn").in_("id", lote)))
    return resultado


def actualizar_jugadas(filas):
    """Reescribe jugadas que ya existen (por ejemplo, con la evaluación nueva)."""
    for lote in en_lotes(filas, 500):
        ejecutar(cliente().table("jugadas").upsert(lote, on_conflict="partida_id,indice"))


# ---------------------------------------------------------------------------
# Caché de evaluaciones
# ---------------------------------------------------------------------------

def leer_evaluaciones(posiciones):
    """{posición: valor} de las que estén guardadas."""
    encontradas = {}
    for lote in en_lotes(sorted(set(posiciones))):
        for fila in ejecutar(cliente().table("evaluaciones").select("posicion,valor")
                             .in_("posicion", lote)):
            encontradas[fila["posicion"]] = fila["valor"]
    return encontradas


def guardar_evaluaciones(valores, profundidad=2):
    """Guarda {posición: valor} (si ya estaba, la reemplaza)."""
    filas = [{"posicion": posicion, "valor": int(valor), "profundidad": profundidad}
             for posicion, valor in valores.items()]
    for lote in en_lotes(filas, 500):
        ejecutar(cliente().table("evaluaciones").upsert(lote, on_conflict="posicion"))


# ---------------------------------------------------------------------------
# Conversión de valores para mandarlos en JSON
# ---------------------------------------------------------------------------

def limpiar(valor):
    """NaN -> None (JSON no tiene NaN), números de pandas -> números de Python,
    fechas -> texto ISO."""
    if valor is None:
        return None
    if hasattr(valor, "isoformat"):            # fechas (Timestamp, datetime)
        try:
            if valor != valor:                 # NaT
                return None
        except TypeError:
            pass
        return valor.isoformat()
    if hasattr(valor, "item"):                 # números de numpy -> Python
        valor = valor.item()
    if isinstance(valor, float) and math.isnan(valor):
        return None
    return valor
