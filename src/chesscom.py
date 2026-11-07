# API pública de Chess.com (sin claves ni login) y verificación de cuentas.
#
#   https://api.chess.com/pub/player/<usuario>
#       -> el perfil (incluye "location", la ubicación que cada uno escribe)
#   https://api.chess.com/pub/player/<usuario>/games/archives
#       -> la lista de "archivos mensuales" (uno por cada mes en que jugaste)
#   https://api.chess.com/pub/player/<usuario>/games/2026/11
#       -> las partidas de ese mes, cada una con su PGN
# Chess.com pide que cada programa se identifique con un User-Agent propio.
#
# Verificar que una cuenta es tuya: Chess.com no da "Iniciar sesión con
# Chess.com" sin aprobación, así que usamos un código: la app genera uno
# (por ejemplo MINIMATE-7K3Q), lo ponés un rato en la "ubicación" de tu perfil
# y la app lo lee con la API. Solo el dueño de la cuenta puede editar su perfil.

import json
import secrets
import time
import urllib.error
import urllib.request

URL_PERFIL = "https://api.chess.com/pub/player/{usuario}"
URL_ARCHIVOS = "https://api.chess.com/pub/player/{usuario}/games/archives"
USER_AGENT = "MiniMate/1.0 (bot de ajedrez educativo; https://github.com/cuervotomas06/minimate)"

# Código de verificación: sin letras que se confunden (O/0, I/1).
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
VENCE_CODIGO = 15 * 60   # segundos


class UsuarioNoEncontrado(Exception):
    pass


def pedir_json(url, intentos=3):
    """Pide una URL de la API y devuelve el JSON. Si Chess.com dice "pará un
    poco" (error 429), espera y vuelve a probar."""
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                  "Accept": "application/json"})
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise UsuarioNoEncontrado(url) from error
            if error.code == 429 and intento < intentos - 1:
                time.sleep(5 * (intento + 1))
                continue
            raise
    raise RuntimeError(f"No se pudo leer {url}")


def bajar_partidas(usuario, meses=None, pedir=None, al_avanzar=None, maximo=None):
    """Lista de textos PGN de tus partidas (solo ajedrez normal, sin variantes),
    de la más vieja a la más nueva.
    meses: si se pasa, solo los últimos N meses.
    maximo: si se pasa, solo las N más recientes.
    pedir: la función que hace los pedidos (los tests le pasan una falsa)."""
    pedir = pedir or pedir_json
    archivos = pedir(URL_ARCHIVOS.format(usuario=usuario.lower()))["archives"]
    desde = None
    if meses is not None:
        archivos = archivos[-meses:]
        desde = time.time() - meses * 30 * 24 * 3600
    partidas = []
    for numero, url in enumerate(archivos, start=1):
        for partida in pedir(url).get("games", []):
            # rules = "chess" es el ajedrez normal (no Chess960, bughouse, etc.).
            if partida.get("rules") != "chess" or not partida.get("pgn"):
                continue
            fin = partida.get("end_time")
            if desde is not None and fin is not None and fin < desde:
                continue
            partidas.append((fin or 0, partida["pgn"]))
        if al_avanzar is not None:
            al_avanzar(numero, len(archivos))
        time.sleep(0.2)  # sin apuro: de a un pedido por vez, como pide Chess.com
    partidas.sort(key=lambda par: par[0])
    pgns = [pgn for _, pgn in partidas]
    return pgns[-maximo:] if maximo else pgns


def perfil(usuario, pedir=None):
    """El perfil público: {"player_id", "username", "location", ...}."""
    pedir = pedir or pedir_json
    return pedir(URL_PERFIL.format(usuario=usuario.strip().lower()))


# ---------------------------------------------------------------------------
# Verificación con código
# ---------------------------------------------------------------------------

def nuevo_codigo(ahora=None):
    """{"codigo": "MINIMATE-7K3Q", "vence": momento} (vence en 15 minutos).
    secrets.choice usa el generador seguro de Python (no se puede adivinar)."""
    ahora = time.time() if ahora is None else ahora
    sufijo = "".join(secrets.choice(ALFABETO) for _ in range(4))
    return {"codigo": f"MINIMATE-{sufijo}", "vence": ahora + VENCE_CODIGO}


def verificar(usuario, pedido, pedir=None, ahora=None):
    """Mira si el código del pedido está en la ubicación del perfil.
    Devuelve (player_id, username) si está. Si no, lanza ValueError con un
    mensaje para mostrar."""
    ahora = time.time() if ahora is None else ahora
    if ahora > pedido["vence"]:
        raise ValueError("El código venció (dura 15 minutos). Generá uno nuevo.")
    try:
        datos = perfil(usuario, pedir)
    except UsuarioNoEncontrado:
        raise ValueError(f"Chess.com no encontró el usuario «{usuario}».") from None
    ubicacion = (datos.get("location") or "").upper()
    if pedido["codigo"].upper() not in ubicacion:
        raise ValueError(
            "Todavía no vemos el código en la ubicación de tu perfil. Guardá el perfil "
            "y probá de nuevo en un minuto (Chess.com a veces tarda en actualizarlo).")
    return str(datos["player_id"]), datos.get("username", usuario)
