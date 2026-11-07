# Lichess: iniciar sesión (OAuth2 con PKCE) y bajar partidas (API pública).
#
# Cómo funciona el inicio de sesión (OAuth2 "authorization code" con PKCE):
# 1. La app inventa dos secretos al azar: "state" y "code_verifier". Del
#    verifier calcula el "code_challenge" (su SHA-256). Te manda a
#    lichess.org/oauth con el challenge y el state.
# 2. Lichess te pregunta si autorizás a MiniMate y te devuelve a la app con
#    ?code=...&state=... en la dirección.
# 3. La app revisa que el state sea uno que ELLA generó, en ESTE navegador
#    (si no, alguien podría mandarte un enlace para que quedes "logueado" con
#    SU cuenta: ataque CSRF) y cambia el code por un token en
#    /api/token, mandando el verifier. Solo quien tiene el verifier (nosotros)
#    puede canjear el code, aunque alguien lo haya visto en la dirección.
# 4. Con el token lee /api/account (id y usuario) y enseguida lo revoca: no lo
#    guardamos en ningún lado, no hace falta.
#
# Lichess no pide registrar la app: el client_id es cualquier texto que la
# identifique. Pedimos CERO permisos (scopes): leer tu id y usuario no necesita
# ninguno. Las partidas se bajan con la API pública, sin token.

import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

URL_AUTORIZAR = "https://lichess.org/oauth"
URL_TOKEN = "https://lichess.org/api/token"
URL_CUENTA = "https://lichess.org/api/account"
URL_PARTIDAS = "https://lichess.org/api/games/user/{usuario}"
CLIENT_ID = "minimate"
USER_AGENT = "MiniMate/1.0 (bot de ajedrez educativo; https://github.com/cuervotomas06/minimate)"
VENCE_PEDIDO = 10 * 60      # segundos para volver de Lichess
# Solo ajedrez normal (sin variantes): estos son los ritmos de juego estándar.
RITMOS = "ultraBullet,bullet,blitz,rapid,classical,correspondence"


class ErrorLichess(Exception):
    """Algo salió mal con Lichess (mensaje para mostrar)."""


# ---------------------------------------------------------------------------
# HTTP (se puede reemplazar en los tests por uno falso)
# ---------------------------------------------------------------------------

class ClienteHttp:
    def _pedido(self, url, metodo="GET", datos=None, token=None, aceptar="application/json"):
        encabezados = {"User-Agent": USER_AGENT, "Accept": aceptar}
        if token:
            encabezados["Authorization"] = f"Bearer {token}"
        cuerpo = urllib.parse.urlencode(datos).encode() if datos is not None else None
        pedido = urllib.request.Request(url, data=cuerpo, headers=encabezados, method=metodo)
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                return respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise ErrorLichess(f"Lichess respondió {error.code}") from error
        except urllib.error.URLError as error:
            raise ErrorLichess("No se pudo conectar con Lichess") from error

    def post_formulario(self, url, datos):
        return json.loads(self._pedido(url, "POST", datos=datos))

    def get_json(self, url, token=None):
        return json.loads(self._pedido(url, token=token))

    def delete(self, url, token):
        self._pedido(url, "DELETE", token=token)

    def get_texto(self, url, aceptar):
        return self._pedido(url, aceptar=aceptar)


# ---------------------------------------------------------------------------
# Inicio de sesión
# ---------------------------------------------------------------------------

# Pedidos pendientes: state -> datos. Viven en la memoria del servidor (no en
# la sesión de Streamlit, porque al volver de Lichess es una sesión nueva).
_pendientes = {}


def _base64url(datos):
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


def nuevo_pedido(redirect_uri, proposito="login", vincular_a=None, ahora=None, navegador=None):
    """Arma la dirección de lichess.org/oauth y guarda el pedido pendiente.
    proposito: "login" (entrar con Lichess) o "vincular" (sumar Lichess a tu
        cuenta de Google ya iniciada; vincular_a dice a qué jugador).
    navegador: una "huella" del navegador que empezó (ver panel_cuenta.py);
        al volver tiene que ser la misma.
    Devuelve la URL a la que hay que ir."""
    ahora = time.time() if ahora is None else ahora
    _limpiar_vencidos(ahora)
    verifier = _base64url(secrets.token_bytes(48))          # 64 caracteres al azar
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    state = _base64url(secrets.token_bytes(24))
    _pendientes[state] = {"verifier": verifier, "creado": ahora, "proposito": proposito,
                          "vincular_a": vincular_a, "redirect_uri": redirect_uri,
                          "navegador": navegador}
    parametros = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        # Sin "scope": no pedimos ningún permiso.
    }
    return f"{URL_AUTORIZAR}?{urllib.parse.urlencode(parametros)}"


def _limpiar_vencidos(ahora):
    for state in [s for s, p in _pendientes.items() if ahora - p["creado"] > VENCE_PEDIDO]:
        del _pendientes[state]


def procesar_retorno(code, state, http=None, ahora=None, navegador=None):
    """Lo que hay que hacer cuando Lichess te devuelve a la app.
    Devuelve {"id", "usuario", "proposito", "vincular_a"}.
    Lanza ErrorLichess si el state no es nuestro, venció o algo falla."""
    ahora = time.time() if ahora is None else ahora
    http = http or ClienteHttp()
    # pop: cada state sirve UNA sola vez (si alguien lo repite, ya no existe).
    pedido = _pendientes.pop(state, None) if state else None
    if pedido is None:
        raise ErrorLichess("El inicio de sesión con Lichess no es válido o ya se usó. "
                           "Probá de nuevo.")
    if ahora - pedido["creado"] > VENCE_PEDIDO:
        raise ErrorLichess("El inicio de sesión con Lichess venció. Probá de nuevo.")
    if pedido["navegador"] is not None and pedido["navegador"] != navegador:
        raise ErrorLichess("El inicio de sesión con Lichess se empezó en otro navegador. "
                           "Probá de nuevo desde acá.")
    if not code:
        raise ErrorLichess("Lichess no autorizó el inicio de sesión.")

    respuesta = http.post_formulario(URL_TOKEN, {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": pedido["verifier"],
        "redirect_uri": pedido["redirect_uri"],
        "client_id": CLIENT_ID,
    })
    token = respuesta.get("access_token")
    if not token:
        raise ErrorLichess("Lichess no dio acceso.")
    try:
        cuenta = http.get_json(URL_CUENTA, token=token)
    finally:
        # No necesitamos el token para nada más: lo revocamos ya.
        try:
            http.delete(URL_TOKEN, token=token)
        except ErrorLichess:
            pass
    if not cuenta.get("id"):
        raise ErrorLichess("Lichess no devolvió la cuenta.")
    return {"id": cuenta["id"], "usuario": cuenta.get("username", cuenta["id"]),
            "proposito": pedido["proposito"], "vincular_a": pedido["vincular_a"]}


# ---------------------------------------------------------------------------
# Partidas (API pública de export)
# ---------------------------------------------------------------------------

def bajar_partidas(usuario, meses=None, maximo=None, http=None, ahora=None):
    """Lista de textos PGN de tus partidas de Lichess (sin variantes), de la
    más vieja a la más nueva. Con relojes ([%clk]) y sin la evaluación de
    Lichess (así todas las evaluaciones son de MiniMate, en la misma escala)."""
    ahora = time.time() if ahora is None else ahora
    http = http or ClienteHttp()
    parametros = {"clocks": "true", "evals": "false", "opening": "true",
                  "perfType": RITMOS, "sort": "dateDesc"}
    if meses is not None:
        parametros["since"] = int((ahora - meses * 30 * 24 * 3600) * 1000)  # milisegundos
    if maximo is not None:
        parametros["max"] = maximo
    url = URL_PARTIDAS.format(usuario=urllib.parse.quote(usuario.lower())) + "?" + \
        urllib.parse.urlencode(parametros)
    texto = http.get_texto(url, aceptar="application/x-chess-pgn")
    # Separamos las partidas con python-chess (más seguro que cortar el texto).
    import io

    import chess.pgn
    pgns = []
    lector = io.StringIO(texto)
    while (juego := chess.pgn.read_game(lector)) is not None:
        if juego.headers.get("Variant", "Standard") == "Standard":
            pgns.append(str(juego))
    return list(reversed(pgns))   # vinieron de la más nueva a la más vieja
