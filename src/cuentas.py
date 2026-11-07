# Cuentas de usuario: quién inició sesión y qué cuentas tiene vinculadas.
#
# Un "jugador" de MiniMate (tabla jugadores) puede tener varias cuentas
# (tabla cuentas, ver supabase/migracion_01_cuentas.sql):
#   - google:   para iniciar sesión (st.login). Se identifica por el "sub",
#               un número que Google da a cada cuenta y que nunca cambia (el
#               email o el nombre sí pueden cambiar, o repetirse).
#   - lichess:  para iniciar sesión o vincularla (OAuth2, ver src/lichess.py).
#   - chesscom: solo vinculada, verificada con un código (src/chesscom.py).
# Cada cuenta externa puede estar vinculada a UN solo jugador.
#
# Este módulo no dibuja nada: la parte visual está en src/panel_cuenta.py.

from src import base_de_datos
from src.jugador import clave_del_nombre, normalizar_nombre


class CuentaDeOtro(Exception):
    """La cuenta ya está vinculada a otro jugador."""


# ---------------------------------------------------------------------------
# Quién inició sesión
# ---------------------------------------------------------------------------

def usuario_google():
    """El usuario de Google si inició sesión (st.user), o None.
    {"proveedor": "google", "id": sub, "nombre", "foto", "email", "email_verificado"}"""
    try:
        import streamlit as st
        if not st.user.get("is_logged_in") or not st.user.get("sub"):
            return None
        return {
            "proveedor": "google",
            "id": str(st.user.get("sub")),
            "nombre": st.user.get("name") or st.user.get("email") or "Jugador",
            "foto": st.user.get("picture"),
            "email": st.user.get("email"),
            "email_verificado": bool(st.user.get("email_verified")),
        }
    except Exception:  # noqa: BLE001  (sin [auth] en secrets, o fuera de Streamlit)
        return None


def google_configurado():
    """True si secrets.toml tiene la sección [auth] para iniciar sesión con Google."""
    try:
        import streamlit as st
        auth = st.secrets.get("auth", {})
        return bool(auth.get("client_id") and auth.get("server_metadata_url"))
    except Exception:  # noqa: BLE001
        return False


def clave_de(identidad):
    """'google:1234...' o 'lichess:usuario': la clave del jugador en la base."""
    return f"{identidad['proveedor']}:{identidad['id']}"


# ---------------------------------------------------------------------------
# De la identidad al jugador
# ---------------------------------------------------------------------------

def jugador_de(identidad):
    """El jugador de esa identidad: {"id", "clave", "nombre"}.
    Con Supabase busca la cuenta vinculada; si es la primera vez, crea el
    jugador y le vincula la cuenta. Sin Supabase, id es None (se guarda en
    archivos, con la clave en el encabezado "Jugador")."""
    nombre = normalizar_nombre(identidad.get("nombre")) or "Jugador"
    clave = clave_de(identidad)
    if not base_de_datos.hay_supabase():
        return {"id": None, "clave": clave, "nombre": nombre}
    cuenta = base_de_datos.buscar_cuenta(identidad["proveedor"], identidad["id"])
    if cuenta is None:
        jugador_id = base_de_datos.id_del_jugador(nombre, clave)
        cuenta = base_de_datos.crear_cuenta(jugador_id, identidad["proveedor"], identidad["id"],
                                            identidad.get("nombre"), verificado=True)
    return {"id": cuenta["jugador_id"], "clave": clave, "nombre": nombre}


# ---------------------------------------------------------------------------
# Vincular cuentas
# ---------------------------------------------------------------------------

def cuentas_de(jugador):
    if not jugador or not jugador.get("id"):
        return []
    return base_de_datos.cuentas_del_jugador(jugador["id"])


def vincular(jugador, proveedor, id_externo, usuario):
    """Vincula una cuenta YA VERIFICADA (Lichess por OAuth, Chess.com por
    código) al jugador. Si ya era suya, no hace nada.

    Si es de otro jugador:
    - Lichess, y ese otro jugador es el que se creó al entrar con esa misma
      cuenta de Lichess (no tiene ninguna otra cuenta): es la misma persona,
      así que juntamos los dos jugadores en uno (partidas incluidas).
    - En cualquier otro caso: CuentaDeOtro (cada cuenta, un solo jugador)."""
    if not jugador or not jugador.get("id"):
        raise ValueError("Para vincular cuentas hace falta la base de datos y una sesión iniciada.")
    existente = base_de_datos.buscar_cuenta(proveedor, id_externo)
    if existente is None:
        existente = base_de_datos.crear_cuenta(jugador["id"], proveedor, id_externo, usuario,
                                               verificado=True)
    if existente["jugador_id"] == jugador["id"]:
        return existente
    otras = base_de_datos.cuentas_del_jugador(existente["jugador_id"])
    if proveedor == "lichess" and [c["proveedor"] for c in otras] == ["lichess"]:
        base_de_datos.fusionar_jugadores(existente["jugador_id"], jugador["id"])
        return base_de_datos.buscar_cuenta(proveedor, id_externo)
    raise CuentaDeOtro(f"Esa cuenta de {nombre_del_proveedor(proveedor)} ya está vinculada "
                       "a otro jugador de MiniMate.")


def nombre_del_proveedor(proveedor):
    return {"google": "Google", "lichess": "Lichess", "chesscom": "Chess.com"}.get(proveedor, proveedor)


# ---------------------------------------------------------------------------
# Pasar las partidas de un jugador viejo (por nombre) a una cuenta
# ---------------------------------------------------------------------------

def migracion_configurada():
    """La sección [migracion] de secrets.toml, o None:
        [migracion]
        jugador_anterior = "mantarraya"
        email = "tu.email@gmail.com"
    """
    try:
        import streamlit as st
        seccion = st.secrets.get("migracion", {})
        if seccion.get("jugador_anterior") and seccion.get("email"):
            return {"jugador_anterior": seccion["jugador_anterior"], "email": seccion["email"]}
    except Exception:  # noqa: BLE001
        pass
    return None


def migrar_si_corresponde(identidad, jugador, configuracion=None):
    """La primera vez que entrás con Google: si secrets.toml dice que el
    jugador viejo "mantarraya" es de tu email (y Google confirma que el email
    es tuyo), pasa esas partidas a tu cuenta. Devuelve cuántas movió, o None.
    El email se usa solo para esta mudanza única que configura el dueño de
    la app; para todo lo demás el jugador se identifica por el "sub"."""
    configuracion = configuracion or migracion_configurada()
    if not configuracion or identidad.get("proveedor") != "google" or not jugador.get("id"):
        return None
    if not identidad.get("email_verificado"):
        return None
    if (identidad.get("email") or "").casefold() != configuracion["email"].casefold():
        return None
    return migrar_jugador(configuracion["jugador_anterior"], jugador["id"])


def migrar_jugador(nombre_anterior, hacia_id):
    """Pasa las partidas del jugador viejo (identificado por nombre, sin
    cuentas) al jugador hacia_id. Devuelve cuántas movió, o None si no hay
    nada que mover (ya se hizo, o no existe)."""
    desde_id = base_de_datos.buscar_jugador(clave_del_nombre(nombre_anterior))
    if desde_id is None or desde_id == hacia_id:
        return None
    if base_de_datos.cuentas_del_jugador(desde_id):
        # Tiene cuentas: no es un jugador "viejo" por nombre. No lo tocamos.
        raise CuentaDeOtro(f"«{nombre_anterior}» tiene cuentas vinculadas: no se migra solo.")
    return base_de_datos.fusionar_jugadores(desde_id, hacia_id)
