# La parte visual de las cuentas (Streamlit): iniciar y cerrar sesión, la
# barra lateral con tu nombre y foto, vincular Lichess y Chess.com, e importar.
# La lógica (sin dibujar nada) está en src/cuentas.py.
#
# Cada página llama primero a preparar_sesion(): procesa la vuelta de Lichess
# (si venís de iniciar sesión allá), averigua el jugador y muestra avisos.

import hashlib
import time
from urllib.parse import urlsplit

import streamlit as st

from src import base_de_datos, chesscom, cuentas, importar, lichess

NOMBRES = {"google": "Google", "lichess": "Lichess", "chesscom": "Chess.com"}


# ---------------------------------------------------------------------------
# Avisos (se muestran arriba de la página, una sola vez)
# ---------------------------------------------------------------------------

def avisar(tipo, texto):
    """tipo: 'success', 'info', 'warning' o 'error'."""
    st.session_state.setdefault("avisos_cuenta", []).append((tipo, texto))


def mostrar_avisos():
    for tipo, texto in st.session_state.pop("avisos_cuenta", []):
        getattr(st, tipo)(texto)


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def identidad_actual():
    """Quién inició sesión: Google (si hay) o Lichess, o None (invitado)."""
    return cuentas.usuario_google() or st.session_state.get("identidad_lichess")


def jugador_actual():
    """El jugador de la sesión {"id", "clave", "nombre"}, o None (invitado).
    Se busca en la base una sola vez por sesión."""
    identidad = identidad_actual()
    if identidad is None:
        return None
    clave = cuentas.clave_de(identidad)
    guardado = st.session_state.get("jugador_sesion")
    if guardado and guardado["clave"] == clave:
        return guardado
    jugador = cuentas.jugador_de(identidad)
    st.session_state.jugador_sesion = jugador
    try:
        movidas = cuentas.migrar_si_corresponde(identidad, jugador)
        if movidas:
            avisar("success", f"Pasamos {movidas} partidas que tenías guardadas a tu cuenta.")
    except cuentas.CuentaDeOtro as error:
        avisar("warning", str(error))
    return jugador


def preparar_sesion():
    """Lo primero de cada página. Devuelve el jugador, o None si sos invitado."""
    procesar_retorno_lichess()
    try:
        jugador = jugador_actual()
    except base_de_datos.ErrorBaseDeDatos as error:
        avisar("error", f"No se pudo conectar con la base de datos ({error}). Por ahora "
                        "jugás como invitado: no se guarda nada.")
        jugador = None
    mostrar_avisos()
    return jugador


def cerrar_sesion():
    """Botón "Cerrar sesión"."""
    con_google = cuentas.usuario_google() is not None
    for clave in ("identidad_lichess", "jugador_sesion", "pedido_lichess_login",
                  "pedido_lichess_vincular", "codigo_chesscom"):
        st.session_state.pop(clave, None)
    if con_google:
        st.logout()


# ---------------------------------------------------------------------------
# Lichess (OAuth2 con PKCE, ver src/lichess.py)
# ---------------------------------------------------------------------------

def redirect_uri_lichess():
    """A dónde vuelve Lichess: [lichess] redirect_uri de secrets.toml.
    Si no está configurada, solo en tu compu (localhost) la deducimos de la
    dirección de la página. En un servidor NO: esa dirección sale de un dato
    del pedido (el encabezado Host) que cualquiera puede falsificar, y un
    atacante podría hacer que Lichess le mande el code a su propio sitio.
    Devuelve None si no hay una dirección segura."""
    try:
        configurado = st.secrets.get("lichess", {}).get("redirect_uri")
    except Exception:  # noqa: BLE001
        configurado = None
    return redirect_seguro(configurado, st.context.url)


def redirect_seguro(configurado, url_de_la_pagina):
    """La parte de redirect_uri_lichess que no depende de Streamlit (para los tests)."""
    if configurado:
        return configurado
    partes = urlsplit(url_de_la_pagina or "http://localhost:8501/")
    if partes.hostname in ("localhost", "127.0.0.1"):
        return f"{partes.scheme}://{partes.netloc}/"
    return None


def huella_navegador():
    """Un identificador de este navegador, para atar el pedido a Lichess al
    navegador que lo empezó. Sale de la cookie anti-XSRF que Streamlit pone
    en cada navegador ("2|máscara|token|fecha": el token es fijo, la máscara
    cambia en cada respuesta, así que lo desenmascaramos). None si no hay."""
    try:
        valor = st.context.cookies.get("_streamlit_xsrf")
    except Exception:  # noqa: BLE001
        valor = None
    return huella_de_cookie(valor)


def huella_de_cookie(valor):
    """La parte de huella_navegador que no depende de Streamlit (para los tests)."""
    if not isinstance(valor, str) or not valor:
        return None
    partes = valor.split("|")
    try:
        if partes[0] == "2":
            mascara, token = bytes.fromhex(partes[1]), bytes.fromhex(partes[2])
            token = bytes(b ^ mascara[i % 4] for i, b in enumerate(token))
        else:
            token = valor.encode()
    except (ValueError, IndexError):
        return None
    return hashlib.sha256(token).hexdigest()[:32]


def url_lichess(proposito):
    """Dirección de lichess.org/oauth. Se arma una vez por sesión (y se renueva
    antes de que venza), así no se crea un pedido nuevo en cada corrida.
    None si no hay una dirección de vuelta segura (ver redirect_uri_lichess)."""
    redirect_uri = redirect_uri_lichess()
    if redirect_uri is None:
        return None
    clave = f"pedido_lichess_{proposito}"
    vincular_a = None
    if proposito == "vincular":
        vincular_a = cuentas.clave_de(identidad_actual())
    guardado = st.session_state.get(clave)
    ahora = time.time()
    if (not guardado or ahora - guardado["creado"] > lichess.VENCE_PEDIDO - 60
            or guardado["vincular_a"] != vincular_a):
        guardado = {"url": lichess.nuevo_pedido(redirect_uri, proposito, vincular_a,
                                                navegador=huella_navegador()),
                    "creado": ahora, "vincular_a": vincular_a}
        st.session_state[clave] = guardado
    return guardado["url"]


def procesar_retorno_lichess():
    """Si la dirección trae ?code=...&state=... es que volvés de Lichess."""
    parametros = st.query_params
    if "state" not in parametros:
        return
    code, state, error = parametros.get("code"), parametros.get("state"), parametros.get("error")
    st.query_params.clear()   # que el code no quede en la dirección
    if error:
        lichess._pendientes.pop(state, None)
        avisar("warning", "No se autorizó el inicio de sesión con Lichess.")
        return
    try:
        datos = lichess.procesar_retorno(code, state, navegador=huella_navegador())
    except lichess.ErrorLichess as problema:
        avisar("error", str(problema))
        return

    if datos["proposito"] == "vincular":
        identidad = identidad_actual()
        # Solo vincula a quien empezó el pedido (si no, otro podría colarte la suya).
        if identidad is None or cuentas.clave_de(identidad) != datos["vincular_a"]:
            avisar("error", "Para vincular Lichess tenés que seguir con la misma sesión "
                            "con la que empezaste.")
            return
        try:
            cuentas.vincular(jugador_actual(), "lichess", datos["id"], datos["usuario"])
            avisar("success", f"Lichess vinculado: **{datos['usuario']}**.")
        except (cuentas.CuentaDeOtro, base_de_datos.ErrorBaseDeDatos, ValueError) as problema:
            avisar("error", str(problema))
    else:
        st.session_state.identidad_lichess = {"proveedor": "lichess", "id": datos["id"],
                                              "nombre": datos["usuario"], "foto": None}
        st.session_state.pop("jugador_sesion", None)
        avisar("success", f"Entraste con Lichess como **{datos['usuario']}**.")


# ---------------------------------------------------------------------------
# Botones e información de la sesión
# ---------------------------------------------------------------------------

def botones_de_inicio(lugar, bloquear=False):
    """Iniciar sesión con Google (si está configurado) o con Lichess.
    bloquear: durante una partida (al iniciar sesión se recarga la página y
    la partida se perdería)."""
    if cuentas.google_configurado():
        st.button("Iniciar sesión con Google", key=f"login_google_{lugar}", on_click=st.login,
                  disabled=bloquear, width="stretch", type="primary")
    url = url_lichess("login")
    if url:
        st.link_button("Iniciar sesión con Lichess", url, disabled=bloquear, width="stretch")
    else:
        st.caption("Para entrar con Lichess falta configurar [lichess] redirect_uri "
                   "(ver docs/LOGIN.md).")
    if bloquear:
        st.caption("Terminá o abandoná la partida para iniciar sesión (si no, se pierde).")


def barra_lateral(bloquear=False):
    """Arriba de la barra lateral: quién sos, o los botones para entrar."""
    with st.sidebar:
        identidad = identidad_actual()
        if identidad:
            if identidad.get("foto"):
                st.image(identidad["foto"], width=48)
            st.markdown(f"**{identidad['nombre']}**  \n"
                        f"con {NOMBRES[identidad['proveedor']]}")
            st.button("Cerrar sesión", key="cerrar_sesion", on_click=cerrar_sesion,
                      disabled=bloquear,
                      help="Terminá o abandoná la partida primero." if bloquear else None)
        else:
            st.markdown("👤 **Invitado**")
            botones_de_inicio("barra", bloquear)
        st.divider()


# ---------------------------------------------------------------------------
# Cuentas vinculadas e importación (página Mis estadísticas)
# ---------------------------------------------------------------------------

def seccion_cuentas(jugador):
    """Tus cuentas de Chess.com y Lichess: vincularlas e importar partidas."""
    if not base_de_datos.hay_supabase():
        st.caption("Vincular cuentas e importar partidas desde la app necesita la base de "
                   "datos (Supabase).")
        return
    vinculadas = cuentas.cuentas_de(jugador)
    por_proveedor = {c["proveedor"]: c for c in vinculadas}
    for cuenta in vinculadas:
        if cuenta["proveedor"] in ("chesscom", "lichess"):
            marca = "✅ verificada" if cuenta.get("verificado") else "sin verificar"
            st.markdown(f"**{NOMBRES[cuenta['proveedor']]}**: {cuenta['usuario']} · {marca}")

    if "lichess" not in por_proveedor:
        url = url_lichess("vincular")
        if url:
            st.link_button("Vincular Lichess", url)
            st.caption("Se abre Lichess en otra pestaña; al autorizar, queda vinculada ahí.")
        else:
            st.caption("Para vincular Lichess falta configurar [lichess] redirect_uri.")
    if "chesscom" not in por_proveedor:
        formulario_chesscom(jugador)

    importables = [c for c in vinculadas
                   if c["proveedor"] in ("chesscom", "lichess") and c.get("verificado")]
    if importables:
        seccion_importar(jugador, importables)

    # Para migrar_jugador.py (pasar partidas viejas a esta cuenta).
    st.caption(f"Tu clave en MiniMate: `{jugador['clave']}`")


def formulario_chesscom(jugador):
    st.markdown("**Vincular Chess.com**")
    usuario = st.text_input("Tu usuario de Chess.com", key="chesscom_usuario").strip()
    if st.button("Generar código", key="chesscom_generar", disabled=not usuario):
        st.session_state.codigo_chesscom = {**chesscom.nuevo_codigo(), "usuario": usuario}
    pedido = st.session_state.get("codigo_chesscom")
    if not pedido:
        return
    minutos = max(0, int((pedido["vence"] - time.time()) // 60))
    st.info(
        f"1. En chess.com entrá a **Configuración → Perfil** y en **Ubicación** escribí:  \n"
        f"`{pedido['codigo']}`  \n"
        f"2. Guardá el perfil y tocá **Verificar**.  \n"
        f"El código vence en {minutos} minutos. Después de verificar ya podés borrarlo "
        f"de tu perfil.")
    if st.button("Verificar", key="chesscom_verificar", type="primary"):
        try:
            player_id, nombre = chesscom.verificar(pedido["usuario"], pedido)
            cuentas.vincular(jugador, "chesscom", player_id, nombre)
        except (ValueError, cuentas.CuentaDeOtro, base_de_datos.ErrorBaseDeDatos) as problema:
            st.error(str(problema))
            return
        st.session_state.pop("codigo_chesscom", None)
        avisar("success", f"Chess.com vinculado y verificado: **{nombre}**. Ya podés borrar "
                          "el código de la ubicación de tu perfil.")
        st.rerun()


def seccion_importar(jugador, importables):
    st.markdown("**Importar partidas**")
    meses = st.radio("Traer las de los últimos", importar.MESES, horizontal=True,
                     format_func=lambda m: f"{m} {'mes' if m == 1 else 'meses'}",
                     key="importar_meses")
    st.caption(f"Como mucho las {importar.MAXIMO_PARTIDAS} más recientes de cada cuenta. Las "
               "que ya tenías no se repiten. MiniMate analiza cada partida nueva (unos "
               "segundos por partida; las posiciones ya vistas salen de la caché).")
    if not st.button("🔄 Actualizar", key="importar_actualizar", type="primary"):
        return
    for cuenta in importables:
        nombre = f"{NOMBRES[cuenta['proveedor']]} ({cuenta['usuario']})"
        barra = st.progress(0.0, text=f"{nombre}: bajando partidas...")
        try:
            nuevas, repetidas = importar.importar_cuenta(
                cuenta, meses,
                al_avanzar=lambda hechas, total, nombre=nombre, barra=barra: barra.progress(
                    hechas / total, text=f"{nombre}: partida {hechas} de {total}"))
            importar.evaluar_pendientes(jugador["id"], cuenta["proveedor"])
        except Exception as problema:  # noqa: BLE001  (sin internet, usuario borrado...)
            avisar("error", f"{nombre}: no se pudo importar "
                            f"({base_de_datos.resumir_error(problema)}).")
            continue
        finally:
            barra.empty()
        avisar("success", f"{nombre}: {nuevas} partidas nuevas, {repetidas} ya estaban.")
    st.session_state.version_datos = st.session_state.get("version_datos", 0) + 1
    st.rerun()
