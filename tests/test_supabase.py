# Tests del guardado y la lectura en Supabase, con la base simulada
# (tests/supabase_falso.py): ninguno se conecta de verdad.
# Los de cuentas (Google, Lichess, Chess.com) están en tests/test_cuentas.py.
# Se corren con: pytest

import math
from datetime import datetime

import chess
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import subir_a_supabase
from src import base_de_datos, cuentas
from src.base_de_datos import credenciales as credenciales_originales
from src.datos import CacheSupabase, cargar_todo, filas_para_base, leer_pgn
from src.guardado import armar_pgn, guardar_partida
from src.jugador import clave_del_nombre, normalizar_nombre
from tests.conftest import USUARIO_DE_PRUEBA
from tests.test_datos import PGN_CHESSCOM, pgn_minimate

FECHA = datetime(2026, 11, 6, 15, 30, 0)
OTRA_PERSONA = {**USUARIO_DE_PRUEBA, "id": "sub-otra-persona", "nombre": "Otra Persona",
                "email": "otra@example.com"}


def jugador_de_prueba(identidad=USUARIO_DE_PRUEBA):
    return cuentas.jugador_de(identidad)


# --- Nombres ------------------------------------------------------------------------

def test_normalizar_nombre():
    assert normalizar_nombre("  Tomás   Amaya ") == "Tomás Amaya"
    assert clave_del_nombre(" TOMÁS ") == clave_del_nombre("tomás")
    assert len(normalizar_nombre("x" * 100)) == 40


# --- Credenciales ---------------------------------------------------------------

def test_credenciales_de_las_variables_de_entorno(monkeypatch):
    import streamlit
    monkeypatch.setattr(streamlit, "secrets", {})      # sin secrets.toml
    assert credenciales_originales() is None
    monkeypatch.setenv("SUPABASE_URL", "https://ejemplo.supabase.co")
    monkeypatch.setenv("SUPABASE_CLAVE", "sb_secret_de_prueba")
    assert credenciales_originales() == ("https://ejemplo.supabase.co", "sb_secret_de_prueba")


def test_credenciales_de_secrets(monkeypatch):
    import streamlit
    monkeypatch.setattr(streamlit, "secrets", {"supabase": {
        "url": "https://ejemplo.supabase.co", "clave": "sb_secret_de_prueba"}})
    assert credenciales_originales() == ("https://ejemplo.supabase.co", "sb_secret_de_prueba")


def test_sin_credenciales_no_hay_supabase():
    assert not base_de_datos.hay_supabase()


# --- Conversión de filas ----------------------------------------------------------

def test_limpiar_valores():
    assert base_de_datos.limpiar(math.nan) is None
    assert base_de_datos.limpiar(pd.NaT) is None
    assert base_de_datos.limpiar(pd.Timestamp("2026-11-06 15:30")) == "2026-11-06T15:30:00"
    import numpy as np
    assert type(base_de_datos.limpiar(np.int64(3))) is int


def test_filas_para_base_con_enteros_y_sin_nan():
    partidas, jugadas = leer_pgn(PGN_CHESSCOM, con_pgn=True)
    [(partida, sus_jugadas)] = filas_para_base(partidas, jugadas)
    assert partida["jugada_enroque"] == 10 and type(partida["jugada_enroque"]) is int
    assert partida["mi_elo"] == 812 and type(partida["mi_elo"]) is int
    assert partida["clave"] == "https://www.chess.com/game/live/123456"
    assert partida["pgn"].startswith("[Event")
    assert "partida" not in partida                    # el id lo pone la base
    assert len(sus_jugadas) == 24
    assert sus_jugadas[0]["eval_antes"] is None         # NaN -> None (JSON)
    assert "origen" not in sus_jugadas[0]               # sale de la partida


# --- Guardar y leer -----------------------------------------------------------------

def test_guardar_en_supabase_y_leer(base, carpeta_de_datos_temporal):
    jugador = jugador_de_prueba()
    assert guardar_partida(pgn_minimate(), jugador) == "Supabase"
    assert len(base.tablas["partidas"]) == 1
    assert len(base.tablas["jugadas"]) == 14
    assert not (carpeta_de_datos_temporal / "partidas.pgn").exists()   # no usó el archivo

    partidas, jugadas = cargar_todo(jugador_id=jugador["id"])
    # Lo que se lee de la base es igual a lo que sale de leer el PGN.
    esperadas, esperadas_jugadas = leer_pgn(pgn_minimate())
    for columna in ("origen", "color", "nivel", "reloj", "resultado", "terminacion",
                    "cantidad_jugadas", "eco", "apertura", "menores_desarrolladas", "clave"):
        assert partidas.iloc[0][columna] == esperadas.iloc[0][columna], columna
    assert partidas.iloc[0]["fecha"] == pd.Timestamp(FECHA)
    assert list(jugadas.columns) == list(esperadas_jugadas.columns)
    for columna in ("san", "es_mia", "eval_antes", "eval_despues", "perdida", "clasificacion"):
        assert jugadas[columna].tolist() == esperadas_jugadas[columna].tolist(), columna
    assert (jugadas["origen"] == "minimate").all()


def test_sin_sesion_no_se_guarda_en_la_base(base):
    with pytest.raises(ValueError):
        guardar_partida(pgn_minimate(), None)
    assert base.tablas["partidas"] == []


def test_no_duplica(base):
    jugador = jugador_de_prueba()
    guardar_partida(pgn_minimate(), jugador)
    guardar_partida(pgn_minimate(), jugador)
    assert len(base.tablas["partidas"]) == 1
    assert len(base.tablas["jugadas"]) == 14


def test_cada_jugador_ve_lo_suyo(base):
    yo, otra = jugador_de_prueba(), jugador_de_prueba(OTRA_PERSONA)
    assert yo["id"] != otra["id"]
    guardar_partida(pgn_minimate(), yo)
    guardar_partida(pgn_minimate("e4 e5 Qh5 Qg5 Qxg5", color=chess.BLACK), otra)
    assert list(cargar_todo(jugador_id=yo["id"])[0]["color"]) == ["blancas"]
    assert list(cargar_todo(jugador_id=otra["id"])[0]["color"]) == ["negras"]


def test_leer_sin_id_de_jugador_no_se_puede(base):
    with pytest.raises(ValueError):
        cargar_todo(jugador_id=None)


def test_si_supabase_falla_se_avisa(base):
    jugador = jugador_de_prueba()
    base.fallar = True
    with pytest.raises(base_de_datos.ErrorBaseDeDatos) as error:
        guardar_partida(pgn_minimate(), jugador)
    assert "Sin conexión" in str(error.value)


def test_cache_de_evaluaciones_en_supabase(base):
    cache = CacheSupabase()
    tablero = chess.Board()
    valor = cache.obtener(tablero)                    # la calcula
    cache.guardar()
    assert base.tablas["evaluaciones"][0]["valor"] == valor
    # Otra caché (otra sesión) la lee de la base en vez de calcularla.
    otra = CacheSupabase()
    otra.precargar([tablero])
    assert otra.buscar(tablero) == valor


# --- Script para subir lo que había en archivos (jugadores viejos, por nombre) ----

def escribir_archivos(carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    vieja = pgn_minimate()                               # sin encabezado Jugador
    tablero = chess.Board()
    tablero.push_san("e4")
    de_ana = armar_pgn(tablero, chess.WHITE, "Fácil", "Sin reloj", abandono=True,
                       fecha=FECHA, jugador="Ana")
    (carpeta / "partidas.pgn").write_text(vieja + "\n\n" + de_ana, encoding="utf-8")
    (carpeta / "chesscom.pgn").write_text(PGN_CHESSCOM, encoding="utf-8")


def partidas_de_nombre(base, nombre):
    jugador_id = base_de_datos.buscar_jugador(clave_del_nombre(nombre))
    return [p for p in base.tablas["partidas"] if p["jugador_id"] == jugador_id]


def test_subir_lo_que_habia(base, carpeta_de_datos_temporal):
    escribir_archivos(carpeta_de_datos_temporal)
    resumen = subir_a_supabase.subir_todo("mantarraya")
    assert resumen["partidas.pgn"] == (2, 0)
    assert resumen["chesscom.pgn"] == (1, 0)
    # La vieja (sin Jugador) y la de Chess.com van a mantarraya; la de Ana, a Ana.
    assert len(partidas_de_nombre(base, "mantarraya")) == 2
    assert len(partidas_de_nombre(base, "Ana")) == 1


def test_subir_dos_veces_no_duplica(base, carpeta_de_datos_temporal):
    escribir_archivos(carpeta_de_datos_temporal)
    subir_a_supabase.subir_todo("mantarraya")
    resumen = subir_a_supabase.subir_todo("mantarraya")
    assert resumen["partidas.pgn"] == (0, 2)
    assert resumen["chesscom.pgn"] == (0, 1)
    assert len(base.tablas["partidas"]) == 3


def test_subir_tambien_la_cache(base, carpeta_de_datos_temporal):
    from src.datos import CacheEvaluaciones
    escribir_archivos(carpeta_de_datos_temporal)
    cache = CacheEvaluaciones(carpeta_de_datos_temporal / "evaluaciones.parquet")
    cache.obtener(chess.Board())
    cache.guardar()
    resumen = subir_a_supabase.subir_todo("mantarraya")
    assert resumen["evaluaciones"] == 1
    assert len(base.tablas["evaluaciones"]) == 1


# --- La app con Supabase ------------------------------------------------------------

RUTA_JUGAR = "../paginas/jugar.py"
RUTA_ESTADISTICAS = "../paginas/estadisticas.py"


def abrir(ruta=RUTA_JUGAR):
    at = AppTest.from_file(ruta, default_timeout=60).run()
    if ruta == RUTA_JUGAR:
        at.select_slider(key="nivel").set_value("Principiante").run()
    return at


def jugar_y_abandonar(at):
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="abandonar").click().run()


def test_la_app_guarda_en_supabase(base, google, carpeta_de_datos_temporal):
    google.entrar()
    at = abrir()
    jugar_y_abandonar(at)
    assert not at.exception
    assert len(base.tablas["partidas"]) == 1
    assert "Supabase" in " ".join(c.value for c in at.caption)
    assert not (carpeta_de_datos_temporal / "partidas.pgn").exists()
    jugador = jugador_de_prueba()
    assert base.tablas["partidas"][0]["jugador_id"] == jugador["id"]


def test_invitado_no_guarda_en_la_base(base):
    at = abrir()                                  # sin sesión
    assert "invitado" in at.info[0].value
    jugar_y_abandonar(at)
    assert not at.exception
    assert base.tablas["partidas"] == []
    assert "no se guardó" in at.warning[-1].value
    assert at.get("download_button")             # pero se puede descargar


def test_si_supabase_falla_la_partida_no_se_pierde(base, google, carpeta_de_datos_temporal):
    google.entrar()
    at = abrir()
    base.fallar = True
    jugar_y_abandonar(at)
    assert not at.exception
    assert "No se pudo guardar" in at.error[-1].value
    assert at.get("download_button")                         # se puede descargar
    assert (carpeta_de_datos_temporal / "partidas.pgn").exists()  # y quedó una copia local
    # Vuelve internet: "Reintentar" la sube y el aviso desaparece.
    base.fallar = False
    at.button(key="reintentar_guardado").click().run()
    assert len(base.tablas["partidas"]) == 1
    assert at.session_state.error_guardado is None
    assert "Supabase" in " ".join(c.value for c in at.caption)
    texto = (carpeta_de_datos_temporal / "partidas.pgn").read_text(encoding="utf-8")
    assert texto.count("[Event ") == 1                       # la copia, una sola vez


def test_si_falla_al_confirmar_nueva_partida_no_empieza_otra(base, google):
    google.entrar()
    at = abrir()
    base.fallar = True
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="nueva_partida").click().run()
    at.button(key="confirmar_cambio").click().run()
    assert not at.exception
    assert len(at.session_state.tablero.move_stack) == 2    # sigue la partida vieja
    assert at.session_state.error_guardado is not None
    assert at.get("download_button")


def test_estadisticas_desde_supabase(base, google):
    guardar_partida(pgn_minimate(), jugador_de_prueba())
    google.entrar()
    at = abrir(RUTA_ESTADISTICAS)
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Partidas jugadas"] == "1"
    # Otra persona no ve las mías.
    google.entrar(**{k: OTRA_PERSONA[k] for k in ("id", "nombre", "email")})
    otra = abrir(RUTA_ESTADISTICAS)
    assert "Cómo empezar" in otra.info[0].value


def test_estadisticas_si_supabase_falla(base, google):
    google.entrar()
    jugador_de_prueba()          # el jugador ya existe
    base.fallar = True
    at = abrir(RUTA_ESTADISTICAS)
    assert not at.exception
    assert at.error


def test_estadisticas_piden_iniciar_sesion(base):
    at = abrir(RUTA_ESTADISTICAS)
    assert "Iniciá sesión" in at.info[0].value
    assert not at.metric
    assert at.get("link_button")             # "Iniciar sesión con Lichess"
