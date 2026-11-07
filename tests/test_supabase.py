# Tests del guardado y la lectura en Supabase, con la base simulada
# (tests/supabase_falso.py): ninguno se conecta de verdad.
# Se corren con: pytest

import math
from datetime import datetime

import chess
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import importar_chesscom as imp
import subir_a_supabase
from src import base_de_datos
from src.base_de_datos import credenciales as credenciales_originales
from src.datos import (CacheSupabase, cargar_todo, filas_para_base, leer_pgn)
from src.guardado import armar_pgn, guardar_partida
from src.jugador import clave_del_nombre, normalizar_nombre
from tests.test_datos import PGN_CHESSCOM, pgn_minimate
from tests.test_importar_chesscom import api_falsa

FECHA = datetime(2026, 11, 6, 15, 30, 0)


# --- Nombre del jugador ---------------------------------------------------------

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
    assert guardar_partida(pgn_minimate(), "Tomás") == "Supabase"
    assert len(base.tablas["jugadores"]) == 1
    assert len(base.tablas["partidas"]) == 1
    assert len(base.tablas["jugadas"]) == 14
    assert not (carpeta_de_datos_temporal / "partidas.pgn").exists()   # no usó el archivo

    partidas, jugadas = cargar_todo(jugador="Tomás")
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


def test_no_duplica(base):
    guardar_partida(pgn_minimate(), "Tomás")
    guardar_partida(pgn_minimate(), "Tomás")
    assert len(base.tablas["partidas"]) == 1
    assert len(base.tablas["jugadas"]) == 14


def test_cada_jugador_ve_lo_suyo(base):
    guardar_partida(pgn_minimate(), "Tomás")
    guardar_partida(pgn_minimate("e4 e5 Qh5 Qg5 Qxg5", color=chess.BLACK), "Ana")
    assert len(cargar_todo(jugador="Tomás")[0]) == 1
    assert len(cargar_todo(jugador=" tomás ")[0]) == 1     # mismo jugador
    ana, _ = cargar_todo(jugador="Ana")
    assert list(ana["color"]) == ["negras"]
    assert cargar_todo(jugador="Nadie")[0].empty


def test_si_supabase_falla_se_avisa(base):
    base.fallar = True
    with pytest.raises(base_de_datos.ErrorBaseDeDatos) as error:
        guardar_partida(pgn_minimate(), "Tomás")
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


# --- Script para subir lo que ya había en archivos ---------------------------------

def escribir_archivos(carpeta):
    carpeta.mkdir(parents=True, exist_ok=True)
    vieja = pgn_minimate()                               # sin encabezado Jugador
    tablero = chess.Board()
    tablero.push_san("e4")
    de_ana = armar_pgn(tablero, chess.WHITE, "Fácil", "Sin reloj", abandono=True,
                       fecha=FECHA, jugador="Ana")
    (carpeta / "partidas.pgn").write_text(vieja + "\n\n" + de_ana, encoding="utf-8")
    (carpeta / "chesscom.pgn").write_text(PGN_CHESSCOM, encoding="utf-8")


def test_subir_lo_que_habia(base, carpeta_de_datos_temporal):
    escribir_archivos(carpeta_de_datos_temporal)
    resumen = subir_a_supabase.subir_todo("Tomás")
    assert resumen["partidas.pgn"] == (2, 0)
    assert resumen["chesscom.pgn"] == (1, 0)
    # La vieja (sin Jugador) y la de Chess.com van a Tomás; la de Ana, a Ana.
    assert len(cargar_todo(jugador="Tomás")[0]) == 2
    assert len(cargar_todo(jugador="Ana")[0]) == 1
    assert set(cargar_todo(jugador="Tomás")[0]["origen"]) == {"minimate", "chesscom"}


def test_subir_dos_veces_no_duplica(base, carpeta_de_datos_temporal):
    escribir_archivos(carpeta_de_datos_temporal)
    subir_a_supabase.subir_todo("Tomás")
    resumen = subir_a_supabase.subir_todo("Tomás")
    assert resumen["partidas.pgn"] == (0, 2)
    assert resumen["chesscom.pgn"] == (0, 1)
    assert len(base.tablas["partidas"]) == 3


def test_subir_tambien_la_cache(base, carpeta_de_datos_temporal):
    from src.datos import CacheEvaluaciones
    escribir_archivos(carpeta_de_datos_temporal)
    cache = CacheEvaluaciones(carpeta_de_datos_temporal / "evaluaciones.parquet")
    cache.obtener(chess.Board())
    cache.guardar()
    resumen = subir_a_supabase.subir_todo("Tomás")
    assert resumen["evaluaciones"] == 1
    assert len(base.tablas["evaluaciones"]) == 1


# --- Importador de Chess.com con Supabase ------------------------------------------

def test_importar_a_supabase_y_evaluar(base, monkeypatch):
    monkeypatch.setattr(imp.time, "sleep", lambda segundos: None)
    assert imp.importar_a_supabase("yo", "Tomás", pedir=api_falsa([])) == (2, 0)
    assert imp.importar_a_supabase("yo", "Tomás", pedir=api_falsa([])) == (0, 2)  # sin duplicar
    partidas, jugadas = cargar_todo(jugador="Tomás")
    assert list(partidas["origen"]) == ["chesscom", "chesscom"]
    assert sorted(partidas["color"]) == ["blancas", "negras"]
    assert jugadas["eval_despues"].isna().any()          # todavía sin evaluar

    assert imp.evaluar_en_supabase("Tomás") == 2
    _, jugadas = cargar_todo(jugador="Tomás")
    assert jugadas["eval_despues"].notna().all()
    assert len(base.tablas["evaluaciones"]) > 0          # la caché quedó en la base
    assert imp.evaluar_en_supabase("Tomás") == 0         # ya no queda nada sin evaluar


# --- La app con Supabase ------------------------------------------------------------

RUTA_JUGAR = "../paginas/jugar.py"
RUTA_ESTADISTICAS = "../paginas/estadisticas.py"


def abrir(ruta=RUTA_JUGAR, jugador="Tomás"):
    at = AppTest.from_file(ruta, default_timeout=60)
    if jugador is not None:
        at.session_state.jugador = jugador
    at.run()
    if ruta == RUTA_JUGAR and jugador is not None:
        at.select_slider(key="nivel").set_value("Principiante").run()
    return at


def jugar_y_abandonar(at):
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="abandonar").click().run()


def test_pide_el_nombre_al_empezar():
    at = abrir(jugador=None)
    assert at.text_input(key="nombre_escrito")
    assert not at.get("component_instance")              # todavía no hay tablero
    at.text_input(key="nombre_escrito").input("  Tomás  ")
    at.button[0].click().run()
    assert at.session_state.jugador == "Tomás"
    assert at.get("component_instance")                  # ahora sí
    assert "Tomás" in at.sidebar.markdown[0].value


def test_nombre_vacio_no_entra():
    at = abrir(jugador=None)
    at.text_input(key="nombre_escrito").input("   ")
    at.button[0].click().run()
    assert "jugador" not in at.session_state or not at.session_state["jugador"]
    assert at.error


def test_cambiar_de_jugador_solo_sin_partida_en_curso():
    at = abrir()
    at.text_input(key="texto_jugada").input("e4").run()
    assert at.button(key="cambiar_jugador").disabled
    at.button(key="abandonar").click().run()
    assert not at.button(key="cambiar_jugador").disabled
    at.button(key="cambiar_jugador").click().run()
    assert not at.session_state.jugador
    assert at.text_input(key="nombre_escrito")


def test_la_app_guarda_en_supabase(base, carpeta_de_datos_temporal):
    at = abrir()
    jugar_y_abandonar(at)
    assert not at.exception
    assert len(base.tablas["partidas"]) == 1
    assert "Supabase" in " ".join(c.value for c in at.caption)
    assert not (carpeta_de_datos_temporal / "partidas.pgn").exists()
    partidas, _ = cargar_todo(jugador="Tomás")
    assert partidas.iloc[0]["terminacion"] == "abandono"


def test_si_supabase_falla_la_partida_no_se_pierde(base, carpeta_de_datos_temporal):
    base.fallar = True
    at = abrir()
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
    # La copia local no se escribió dos veces.
    texto = (carpeta_de_datos_temporal / "partidas.pgn").read_text(encoding="utf-8")
    assert texto.count("[Event ") == 1


def test_si_falla_al_confirmar_nueva_partida_no_empieza_otra(base):
    base.fallar = True
    at = abrir()
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="nueva_partida").click().run()
    at.button(key="confirmar_cambio").click().run()
    assert not at.exception
    assert len(at.session_state.tablero.move_stack) == 2    # sigue la partida vieja
    assert at.session_state.error_guardado is not None
    assert at.get("download_button")


def test_estadisticas_desde_supabase(base):
    guardar_partida(pgn_minimate(), "Tomás")
    at = abrir(RUTA_ESTADISTICAS)
    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Partidas jugadas"] == "1"
    # Otro jugador no ve las de Tomás.
    otro = abrir(RUTA_ESTADISTICAS, jugador="Ana")
    assert "Cómo empezar" in otro.info[0].value


def test_estadisticas_si_supabase_falla(base):
    base.fallar = True
    at = abrir(RUTA_ESTADISTICAS)
    assert not at.exception
    assert "No se pudieron leer" in at.error[0].value


def test_estadisticas_piden_el_nombre():
    at = abrir(RUTA_ESTADISTICAS, jugador=None)
    assert at.text_input(key="nombre_escrito")
    assert not at.metric
