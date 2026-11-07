# Tests de cuentas: Google, Lichess y Chess.com (todo simulado), cómo se
# vinculan, la importación y que nadie vea ni toque los datos de otro.
# Se corren con: pytest

import base64
import hashlib
import io
import time
import urllib.parse

import chess
import chess.pgn
import pytest
from streamlit.testing.v1 import AppTest

import importar_chesscom
import migrar_jugador
from src import base_de_datos, chesscom, cuentas, importar, lichess
from src.datos import cargar_todo, leer_pgn
from src.guardado import guardar_partida, subir_partidas
from tests.conftest import USUARIO_DE_PRUEBA
from tests.test_datos import pgn_minimate

RUTA_JUGAR = "../paginas/jugar.py"
RUTA_ESTADISTICAS = "../paginas/estadisticas.py"
REDIRECT = "http://localhost:8501/"


# ---------------------------------------------------------------------------
# Servicios simulados
# ---------------------------------------------------------------------------

def pgn_de(jugadas_san, blancas, negras, encabezados):
    tablero = chess.Board()
    for san in jugadas_san.split():
        tablero.push_san(san)
    juego = chess.pgn.Game.from_board(tablero)
    juego.headers["White"], juego.headers["Black"] = blancas, negras
    juego.headers["Result"] = tablero.result() if tablero.is_game_over() else "1-0"
    for clave, valor in encabezados.items():
        juego.headers[clave] = valor
    return str(juego)


PGN_LICHESS = "\n\n\n".join([
    pgn_de("e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#", "Mantarraya", "rival1",
           {"Site": "https://lichess.org/AAAA1111", "UTCDate": "2026.11.05", "UTCTime": "10:00:00",
            "TimeControl": "180+2", "Termination": "Normal", "ECO": "C23",
            "Opening": "Bishop's Opening", "Variant": "Standard"}),
    pgn_de("d4 d5", "rival2", "Mantarraya",
           {"Site": "https://lichess.org/BBBB2222", "UTCDate": "2026.11.04", "UTCTime": "10:00:00",
            "TimeControl": "300+0", "Termination": "Time forfeit"}),
    pgn_de("e4 e5", "Mantarraya", "rival3",
           {"Site": "https://lichess.org/CCCC3333", "Variant": "Chess960"}),   # no se importa
])


class LichessFalso:
    """Simula lichess.org: /api/token, /api/account y el export de partidas."""

    def __init__(self, cuenta_id="mantarraya", usuario="Mantarraya"):
        self.cuenta = {"id": cuenta_id, "username": usuario}
        self.pedidos = []
        self.revocados = []

    def post_formulario(self, url, datos):
        self.pedidos.append(("POST", url, datos))
        assert url == lichess.URL_TOKEN
        return {"access_token": "token-de-prueba", "expires_in": 3600}

    def get_json(self, url, token=None):
        self.pedidos.append(("GET", url, token))
        assert url == lichess.URL_CUENTA and token == "token-de-prueba"
        return dict(self.cuenta)

    def delete(self, url, token):
        self.revocados.append(token)

    def get_texto(self, url, aceptar):
        self.pedidos.append(("GET", url, aceptar))
        return PGN_LICHESS


@pytest.fixture
def lichess_falso(monkeypatch):
    falso = LichessFalso()
    monkeypatch.setattr(lichess, "ClienteHttp", lambda: falso)
    return falso


def partida_chesscom(numero, fin, blancas="mantarraya1938", negras="otro"):
    return {"rules": "chess", "end_time": fin, "pgn": pgn_de(
        "e4 e5 Nf3 Nc6", blancas, negras,
        {"Site": "Chess.com", "Link": f"https://www.chess.com/game/live/{numero}",
         "UTCDate": "2026.11.01", "UTCTime": "10:00:00", "TimeControl": "600"})}


class ChesscomFalso:
    """Simula la API pública de Chess.com (perfil y archivos mensuales)."""

    def __init__(self):
        ahora = time.time()
        self.ubicacion = "Buenos Aires"
        self.archivos = {
            "https://api.chess.com/pub/player/mantarraya1938/games/2026/10":
                [partida_chesscom(1, ahora - 40 * 24 * 3600)],
            "https://api.chess.com/pub/player/mantarraya1938/games/2026/11":
                [partida_chesscom(2, ahora - 3600), partida_chesscom(3, ahora - 60)],
        }

    def __call__(self, url):
        if url == chesscom.URL_PERFIL.format(usuario="mantarraya1938"):
            return {"player_id": 98765, "username": "Mantarraya1938", "location": self.ubicacion}
        if url == chesscom.URL_ARCHIVOS.format(usuario="mantarraya1938"):
            return {"archives": list(self.archivos)}
        if url in self.archivos:
            return {"games": self.archivos[url]}
        raise chesscom.UsuarioNoEncontrado(url)


@pytest.fixture
def chesscom_falso(monkeypatch):
    falso = ChesscomFalso()
    monkeypatch.setattr(chesscom, "pedir_json", falso)
    monkeypatch.setattr(chesscom.time, "sleep", lambda segundos: None)
    return falso


def abrir(ruta=RUTA_JUGAR, parametros=None):
    at = AppTest.from_file(ruta, default_timeout=60)
    for clave, valor in (parametros or {}).items():
        at.query_params[clave] = valor
    return at.run()


def iniciar_pedido_lichess(proposito="login", vincular_a=None):
    """Como si hubieras tocado el botón: devuelve el state del pedido."""
    url = lichess.nuevo_pedido(REDIRECT, proposito, vincular_a)
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

def test_google_se_identifica_por_sub_no_por_email(base):
    yo = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    assert yo["clave"] == "google:sub-prueba-0001"
    # Mismo sub, otro email y otro nombre: el mismo jugador.
    cambiado = {**USUARIO_DE_PRUEBA, "email": "nuevo@example.com", "nombre": "Otro Nombre"}
    assert cuentas.jugador_de(cambiado)["id"] == yo["id"]
    # Mismo email pero otro sub: OTRO jugador.
    impostor = {**USUARIO_DE_PRUEBA, "id": "sub-impostor"}
    assert cuentas.jugador_de(impostor)["id"] != yo["id"]
    [cuenta] = [c for c in base.tablas["cuentas"] if c["id_externo"] == "sub-prueba-0001"]
    assert cuenta["proveedor"] == "google" and cuenta["verificado"]


def test_barra_lateral_con_sesion(google):
    google.entrar(foto="https://ejemplo.com/foto.png")
    at = abrir()
    assert "Persona de Prueba" in at.sidebar.markdown[0].value
    assert at.button(key="cerrar_sesion")
    assert at.sidebar.get("image")                        # la foto
    assert not [i for i in at.info if "invitado" in i.value]


def test_invitado_ve_el_aviso_y_los_botones():
    at = abrir()
    assert "invitado" in at.info[0].value
    assert "Invitado" in at.sidebar.markdown[0].value
    [boton] = at.get("link_button")
    assert "Lichess" in boton.proto.label
    assert boton.proto.url.startswith("https://lichess.org/oauth?")
    # Sin [auth] configurado no aparece "Iniciar sesión con Google".
    assert not [b for b in at.button if (b.key or "").startswith("login_google")]


def test_boton_de_google_si_esta_configurado(monkeypatch):
    monkeypatch.setattr(cuentas, "google_configurado", lambda: True)
    at = abrir()
    assert at.button(key="login_google_barra").label == "Iniciar sesión con Google"


def test_no_se_puede_entrar_ni_salir_en_medio_de_una_partida(google):
    at = abrir()
    at.text_input(key="texto_jugada").input("e4").run()
    assert at.get("link_button")[0].proto.disabled      # entrar con Lichess
    google.entrar()
    at.run()
    assert at.button(key="cerrar_sesion").disabled


def test_sin_supabase_guarda_en_archivo_con_la_clave(google, carpeta_de_datos_temporal):
    google.entrar()
    at = abrir()
    at.select_slider(key="nivel").set_value("Principiante").run()
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="abandonar").click().run()
    texto = (carpeta_de_datos_temporal / "partidas.pgn").read_text(encoding="utf-8")
    assert '[Jugador "google:sub-prueba-0001"]' in texto
    assert '[White "Persona de Prueba"]' in texto
    # Otra persona no ve esa partida en sus estadísticas (archivo local).
    _, jugadas = cargar_todo(jugador="google:otra-persona")
    assert jugadas.empty


def test_cerrar_sesion(monkeypatch, google):
    google.entrar()
    salidas = []
    import streamlit
    monkeypatch.setattr(streamlit, "logout", lambda: salidas.append(1))
    at = abrir()
    at.button(key="cerrar_sesion").click().run()
    assert salidas == [1]


# ---------------------------------------------------------------------------
# Lichess: OAuth2 con PKCE
# ---------------------------------------------------------------------------

def test_url_de_autorizacion_con_pkce():
    url = lichess.nuevo_pedido(REDIRECT)
    partes = urllib.parse.urlsplit(url)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == "https://lichess.org/oauth"
    parametros = {k: v[0] for k, v in urllib.parse.parse_qs(partes.query).items()}
    assert parametros["response_type"] == "code"
    assert parametros["client_id"] == "minimate"
    assert parametros["redirect_uri"] == REDIRECT
    assert parametros["code_challenge_method"] == "S256"
    assert "scope" not in parametros                       # ningún permiso
    pedido = lichess._pendientes[parametros["state"]]
    # El challenge es el SHA-256 del verifier (en base64url, sin "=").
    esperado = base64.urlsafe_b64encode(
        hashlib.sha256(pedido["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert parametros["code_challenge"] == esperado
    assert len(pedido["verifier"]) >= 43


def test_cada_pedido_tiene_su_state():
    assert iniciar_pedido_lichess() != iniciar_pedido_lichess()


def test_procesar_retorno(lichess_falso):
    state = iniciar_pedido_lichess()
    verifier = lichess._pendientes[state]["verifier"]
    datos = lichess.procesar_retorno("code-123", state)
    assert (datos["id"], datos["usuario"], datos["proposito"]) == ("mantarraya", "Mantarraya", "login")
    _, url, formulario = lichess_falso.pedidos[0]
    assert formulario["code_verifier"] == verifier and formulario["code"] == "code-123"
    assert formulario["redirect_uri"] == REDIRECT
    assert lichess_falso.revocados == ["token-de-prueba"]   # el token no se guarda: se revoca


def test_state_desconocido_o_repetido(lichess_falso):
    with pytest.raises(lichess.ErrorLichess):
        lichess.procesar_retorno("code", "state-inventado")
    state = iniciar_pedido_lichess()
    lichess.procesar_retorno("code", state)
    with pytest.raises(lichess.ErrorLichess):
        lichess.procesar_retorno("code", state)         # cada state sirve una vez


def test_pedido_vencido(lichess_falso):
    url = lichess.nuevo_pedido(REDIRECT, ahora=time.time() - lichess.VENCE_PEDIDO - 5)
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    with pytest.raises(lichess.ErrorLichess, match="venció"):
        lichess.procesar_retorno("code", state)


def test_el_pedido_queda_atado_al_navegador(lichess_falso):
    # Login CSRF: alguien empieza el pedido en SU navegador y te manda el
    # enlace de vuelta. Desde otro navegador no sirve.
    url = lichess.nuevo_pedido(REDIRECT, navegador="huella-del-atacante")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    with pytest.raises(lichess.ErrorLichess, match="otro navegador"):
        lichess.procesar_retorno("code", state, navegador="huella-de-la-victima")
    # Desde el mismo navegador, sí.
    url = lichess.nuevo_pedido(REDIRECT, navegador="mi-huella")
    state = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["state"][0]
    assert lichess.procesar_retorno("code", state, navegador="mi-huella")["id"] == "mantarraya"


def test_huella_del_navegador_no_cambia_con_la_mascara():
    from src.panel_cuenta import huella_de_cookie
    token = bytes(range(16))

    def cookie(mascara):
        enmascarado = bytes(b ^ mascara[i % 4] for i, b in enumerate(token))
        return f"2|{mascara.hex()}|{enmascarado.hex()}|1700000000"

    # Streamlit cambia la máscara en cada respuesta, pero es el mismo navegador.
    assert huella_de_cookie(cookie(b"\x01\x02\x03\x04")) == huella_de_cookie(cookie(b"\xaa\xbb\xcc\xdd"))
    otro = "2|01020304|" + bytes(16).hex() + "|1700000000"
    assert huella_de_cookie(otro) != huella_de_cookie(cookie(b"\x01\x02\x03\x04"))
    assert huella_de_cookie(None) is None
    assert huella_de_cookie("2|zz|no-es-hex|1") is None     # cookie rota


def test_direccion_de_vuelta_segura():
    from src.panel_cuenta import redirect_seguro
    # En tu compu se deduce de la página.
    assert redirect_seguro(None, "http://localhost:8501/Mis_estadisticas?x=1") == \
        "http://localhost:8501/"
    # En un servidor, NO (el Host del pedido se puede falsificar): hay que configurarla.
    assert redirect_seguro(None, "https://sitio-del-atacante.com/") is None
    assert redirect_seguro("https://minimate.streamlit.app/", "https://otra-cosa.com/") == \
        "https://minimate.streamlit.app/"


def test_entrar_con_lichess_en_la_app(base, lichess_falso):
    state = iniciar_pedido_lichess()
    at = abrir(parametros={"code": "code-123", "state": state})
    assert not at.exception
    assert "Mantarraya" in at.success[0].value
    assert "Mantarraya" in at.sidebar.markdown[0].value
    assert "con Lichess" in at.sidebar.markdown[0].value
    assert at.query_params.get("code") is None            # se borra de la dirección
    # La partida se guarda a nombre del jugador de Lichess.
    at.select_slider(key="nivel").set_value("Principiante").run()
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="abandonar").click().run()
    cuenta = base_de_datos.buscar_cuenta("lichess", "mantarraya")
    assert base.tablas["partidas"][0]["jugador_id"] == cuenta["jugador_id"]


def test_retorno_con_state_falso_no_inicia_sesion(base, lichess_falso):
    at = abrir(parametros={"code": "code-123", "state": "inventado"})
    assert at.error
    assert "Invitado" in at.sidebar.markdown[0].value


def test_vincular_lichess_a_google(base, google, lichess_falso):
    google.entrar()
    yo = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    state = iniciar_pedido_lichess("vincular", vincular_a="google:sub-prueba-0001")
    at = abrir(parametros={"code": "c", "state": state})
    assert "Lichess vinculado" in at.success[0].value
    assert base_de_datos.buscar_cuenta("lichess", "mantarraya")["jugador_id"] == yo["id"]


def test_no_se_puede_vincular_a_la_sesion_de_otro(base, google, lichess_falso):
    # El pedido lo empezó "sub-prueba-0001", pero vuelve otra persona.
    state = iniciar_pedido_lichess("vincular", vincular_a="google:sub-prueba-0001")
    google.entrar(id="sub-de-otra-persona")
    at = abrir(parametros={"code": "c", "state": state})
    assert at.error
    assert base_de_datos.buscar_cuenta("lichess", "mantarraya") is None


def test_entrar_con_lichess_y_despues_vincularlo_a_google_junta_las_partidas(base, google):
    # 1) Entraste con Lichess y jugaste.
    de_lichess = cuentas.jugador_de({"proveedor": "lichess", "id": "mantarraya",
                                     "nombre": "Mantarraya"})
    guardar_partida(pgn_minimate(), de_lichess)
    # 2) Después entrás con Google y vinculás ese mismo Lichess.
    yo = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    cuentas.vincular(yo, "lichess", "mantarraya", "Mantarraya")
    partidas, _ = cargar_todo(jugador_id=yo["id"])
    assert len(partidas) == 1                                 # la partida pasó a tu cuenta
    assert base_de_datos.buscar_jugador("lichess:mantarraya") is None


def test_una_cuenta_de_lichess_no_puede_ser_de_dos_jugadores(base):
    a = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    cuentas.vincular(a, "lichess", "mantarraya", "Mantarraya")
    b = cuentas.jugador_de({**USUARIO_DE_PRUEBA, "id": "sub-b"})
    with pytest.raises(cuentas.CuentaDeOtro):
        cuentas.vincular(b, "lichess", "mantarraya", "Mantarraya")
    assert base_de_datos.buscar_cuenta("lichess", "mantarraya")["jugador_id"] == a["id"]


# ---------------------------------------------------------------------------
# Chess.com: verificación con código
# ---------------------------------------------------------------------------

def test_codigo_de_verificacion():
    pedido = chesscom.nuevo_codigo(ahora=1000)
    assert pedido["codigo"].startswith("MINIMATE-") and len(pedido["codigo"]) == 13
    assert set(pedido["codigo"][9:]) <= set(chesscom.ALFABETO)
    assert pedido["vence"] == 1000 + 15 * 60


def test_verificar_chesscom(chesscom_falso):
    pedido = chesscom.nuevo_codigo()
    with pytest.raises(ValueError, match="Todavía no vemos"):
        chesscom.verificar("mantarraya1938", pedido)
    chesscom_falso.ubicacion = f"Buenos Aires {pedido['codigo'].lower()}"
    assert chesscom.verificar("Mantarraya1938", pedido) == ("98765", "Mantarraya1938")


def test_codigo_vencido(chesscom_falso):
    pedido = chesscom.nuevo_codigo(ahora=time.time() - 16 * 60)
    chesscom_falso.ubicacion = pedido["codigo"]
    with pytest.raises(ValueError, match="venció"):
        chesscom.verificar("mantarraya1938", pedido)


def test_usuario_de_chesscom_que_no_existe(chesscom_falso):
    with pytest.raises(ValueError, match="no encontró"):
        chesscom.verificar("nadie", chesscom.nuevo_codigo())


def test_vincular_chesscom_desde_la_app(base, google, chesscom_falso):
    google.entrar()
    at = abrir(RUTA_ESTADISTICAS)
    at.text_input(key="chesscom_usuario").input("mantarraya1938").run()
    at.button(key="chesscom_generar").click().run()
    codigo = at.session_state.codigo_chesscom["codigo"]
    assert codigo in " ".join(i.value for i in at.info)
    # Sin poner el código en el perfil, no se vincula.
    at.button(key="chesscom_verificar").click().run()
    assert at.error and base_de_datos.buscar_cuenta("chesscom", "98765") is None
    # Con el código en la ubicación, sí.
    chesscom_falso.ubicacion = codigo
    at.button(key="chesscom_verificar").click().run()
    assert not at.exception
    cuenta = base_de_datos.buscar_cuenta("chesscom", "98765")
    assert cuenta["verificado"] and cuenta["usuario"] == "Mantarraya1938"
    assert cuenta["jugador_id"] == cuentas.jugador_de(USUARIO_DE_PRUEBA)["id"]
    assert "borrar" in at.success[0].value                  # avisa que puede borrar el código


def test_chesscom_de_otro_jugador(base):
    a = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    b = cuentas.jugador_de({**USUARIO_DE_PRUEBA, "id": "sub-b"})
    cuentas.vincular(a, "chesscom", "98765", "Mantarraya1938")
    with pytest.raises(cuentas.CuentaDeOtro):
        cuentas.vincular(b, "chesscom", "98765", "Mantarraya1938")


# ---------------------------------------------------------------------------
# Importar partidas de cuentas vinculadas
# ---------------------------------------------------------------------------

def cuenta_vinculada(proveedor, id_externo, usuario, identidad=USUARIO_DE_PRUEBA):
    jugador = cuentas.jugador_de(identidad)
    return jugador, cuentas.vincular(jugador, proveedor, id_externo, usuario)


def test_solo_cuentas_verificadas(base):
    jugador = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    sin_verificar = {"proveedor": "chesscom", "usuario": "x", "verificado": False,
                     "jugador_id": jugador["id"]}
    with pytest.raises(importar.CuentaNoVerificada):
        importar.importar_cuenta(sin_verificar)


def test_importar_chesscom(base, chesscom_falso):
    jugador, cuenta = cuenta_vinculada("chesscom", "98765", "mantarraya1938")
    # Último mes: la de hace 40 días queda afuera.
    assert importar.importar_cuenta(cuenta, meses=1, evaluar=False) == (2, 0)
    assert importar.importar_cuenta(cuenta, meses=1, evaluar=False) == (0, 2)   # sin duplicados
    partidas, _ = cargar_todo(jugador_id=jugador["id"])
    assert set(partidas["origen"]) == {"chesscom"}
    assert set(partidas["color"]) == {"blancas"}
    # Con 3 meses entra la tercera.
    assert importar.importar_cuenta(cuenta, meses=3, evaluar=False) == (1, 2)


def test_importar_respeta_el_maximo(base, chesscom_falso):
    _, cuenta = cuenta_vinculada("chesscom", "98765", "mantarraya1938")
    assert importar.importar_cuenta(cuenta, meses=6, maximo=1, evaluar=False) == (1, 0)
    assert base.tablas["partidas"][0]["clave"].endswith("/3")      # la más reciente


def test_importar_evalua_con_cache(base, chesscom_falso):
    jugador, cuenta = cuenta_vinculada("chesscom", "98765", "mantarraya1938")
    importar.importar_cuenta(cuenta, meses=1, evaluar=True)
    _, jugadas = cargar_todo(jugador_id=jugador["id"])
    assert jugadas["eval_despues"].notna().all()
    assert len(base.tablas["evaluaciones"]) > 0
    # Las dos partidas empiezan igual: las posiciones repetidas salen de la caché.
    assert len(base.tablas["evaluaciones"]) < len(jugadas) + 2


def test_importar_lichess(base, lichess_falso):
    jugador, cuenta = cuenta_vinculada("lichess", "mantarraya", "Mantarraya")
    assert importar.importar_cuenta(cuenta, meses=1, evaluar=False) == (2, 0)
    partidas, _ = cargar_todo(jugador_id=jugador["id"])
    assert set(partidas["origen"]) == {"lichess"}
    fila = partidas.sort_values("fecha").iloc[-1]                   # la del mate
    assert (fila["color"], fila["resultado"], fila["terminacion"]) == \
        ("blancas", "victoria", "jaque mate")
    assert fila["apertura"] == "Bishop's Opening"
    assert sorted(partidas["clave"]) == ["https://lichess.org/AAAA1111",
                                          "https://lichess.org/BBBB2222"]
    # Pidió solo ajedrez normal, con relojes y sin la evaluación de Lichess.
    _, url, _ = [p for p in lichess_falso.pedidos if "games/user" in p[1]][0]
    assert "evals=false" in url and "clocks=true" in url and "max=100" in url


def test_terminaciones_de_lichess():
    # Lichess dice "Normal" para un mate (lo deducimos del tablero) y
    # "Time forfeit" para el tiempo.
    partidas, _ = leer_pgn(PGN_LICHESS, usuario="mantarraya")
    assert list(partidas["terminacion"])[:2] == ["jaque mate", "tiempo"]


def test_importar_desde_la_app(base, google, chesscom_falso):
    google.entrar()
    jugador, _ = cuenta_vinculada("chesscom", "98765", "mantarraya1938")
    at = abrir(RUTA_ESTADISTICAS)
    at.radio(key="importar_meses").set_value(1).run()
    at.button(key="importar_actualizar").click().run()
    assert not at.exception
    assert "2 partidas nuevas" in " ".join(s.value for s in at.success)
    assert {m.label: m.value for m in at.metric}["Partidas jugadas"] == "2"


def test_la_app_no_muestra_cuentas_de_otro(base, google, chesscom_falso):
    cuenta_vinculada("chesscom", "98765", "mantarraya1938")         # de Persona de Prueba
    google.entrar(id="sub-de-otra-persona", nombre="Otra Persona")
    at = abrir(RUTA_ESTADISTICAS)
    assert not [b for b in at.button if b.key == "importar_actualizar"]
    assert "Mantarraya1938" not in " ".join(m.value for m in at.markdown)


def test_script_solo_importa_cuentas_vinculadas(base, chesscom_falso):
    assert importar_chesscom.cuenta_vinculada("mantarraya1938") is None
    _, cuenta = cuenta_vinculada("chesscom", "98765", "Mantarraya1938")
    assert importar_chesscom.cuenta_vinculada("mantarraya1938")["id"] == cuenta["id"]


# ---------------------------------------------------------------------------
# Pasar las partidas viejas ("mantarraya") a la cuenta de Google
# ---------------------------------------------------------------------------

def partidas_viejas(base, nombre="mantarraya"):
    subir_partidas(pgn_minimate(), jugador=nombre)
    return base_de_datos.buscar_jugador(nombre)


CONFIGURACION = {"jugador_anterior": "mantarraya", "email": "prueba@example.com"}


def test_migracion_automatica_al_entrar(base):
    vieja = partidas_viejas(base)
    yo = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    assert cuentas.migrar_si_corresponde(USUARIO_DE_PRUEBA, yo, CONFIGURACION) == 1
    assert len(cargar_todo(jugador_id=yo["id"])[0]) == 1
    assert base_de_datos.buscar_jugador("mantarraya") is None and vieja
    # La segunda vez ya no hay nada que mover.
    assert cuentas.migrar_si_corresponde(USUARIO_DE_PRUEBA, yo, CONFIGURACION) is None


def test_migracion_solo_con_el_email_verificado_correcto(base):
    partidas_viejas(base)
    otro = {**USUARIO_DE_PRUEBA, "id": "sub-otro", "email": "otro@example.com"}
    sin_verificar = {**USUARIO_DE_PRUEBA, "id": "sub-x", "email_verificado": False}
    for identidad in (otro, sin_verificar):
        jugador = cuentas.jugador_de(identidad)
        assert cuentas.migrar_si_corresponde(identidad, jugador, CONFIGURACION) is None
    assert base_de_datos.buscar_jugador("mantarraya") is not None


def test_migracion_en_la_app(base, google, monkeypatch):
    partidas_viejas(base)
    monkeypatch.setattr(cuentas, "migracion_configurada", lambda: CONFIGURACION)
    google.entrar()
    at = abrir(RUTA_ESTADISTICAS)
    assert "Pasamos 1 partidas" in at.success[0].value
    assert {m.label: m.value for m in at.metric}["Partidas jugadas"] == "1"


def test_migracion_a_mano(base):
    partidas_viejas(base)
    with pytest.raises(ValueError, match="Iniciaste sesión"):
        migrar_jugador.migrar("mantarraya", "google:sub-prueba-0001")
    cuentas.jugador_de(USUARIO_DE_PRUEBA)
    assert migrar_jugador.migrar("mantarraya", "google:sub-prueba-0001") == 1
    with pytest.raises(ValueError, match="ya se migró"):
        migrar_jugador.migrar("mantarraya", "google:sub-prueba-0001")


def test_no_se_migra_un_jugador_con_cuentas(base):
    a = cuentas.jugador_de(USUARIO_DE_PRUEBA)
    b = cuentas.jugador_de({**USUARIO_DE_PRUEBA, "id": "sub-b"})
    with pytest.raises(cuentas.CuentaDeOtro):
        cuentas.migrar_jugador("google:sub-b", a["id"])
    assert b["id"] != a["id"]


def test_pgn_lichess_se_lee_con_su_usuario():
    partidas, _ = leer_pgn(io.StringIO(PGN_LICHESS).getvalue(), usuario="Mantarraya")
    assert len(partidas) == 3                        # leer_pgn no filtra variantes
    assert set(partidas["origen"]) == {"lichess"}
