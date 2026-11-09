# Tests de la calidad de cada jugada en vivo (★ ✓ ?! ? ??), de cómo se guarda,
# del tiempo del bot con reloj y del cálculo del Elo de medir_elo.py.
# Se corren con: pytest

import io
import json

import chess
import chess.pgn
import pytest
from streamlit.testing.v1 import AppTest

from medir_elo import elo_combinado, profundidad_para_tiempo
from src import analisis
from src.analisis import SIMBOLOS_CALIDAD, analizar_jugada, calidad_de, revisar_partida
from src.datos import calidad_del_comentario, leer_pgn
from src.guardado import armar_pgn
from src.reloj import tiempo_para_el_bot

RUTA_JUGAR = "../paginas/jugar.py"


# --- Clasificación -----------------------------------------------------------------

def test_calidad_de_cada_jugada():
    tablero = chess.Board()
    mejor = analizar_jugada(tablero, chess.Move.from_uci("b1c3"))
    assert mejor["calidad"] in ("mejor", "buena")
    # Regalar la dama (Qd5?? y la torre de d8 la come): error grave.
    tablero = chess.Board("3rk3/8/8/8/8/8/3Q4/4K3 w - - 0 1")
    regalo = analizar_jugada(tablero, chess.Move.from_uci("d2d5"))
    assert regalo["calidad"] == "error grave"
    assert regalo["mejor_san"] != "Qd5"


def test_mejor_y_buena():
    base = {"san": "e4", "mejor_san": "e4", "clasificacion": None}
    assert calidad_de(base) == "mejor"
    assert calidad_de({**base, "mejor_san": "d4"}) == "buena"
    assert calidad_de({**base, "mejor_san": "d4", "clasificacion": "error"}) == "error"
    assert [SIMBOLOS_CALIDAD[c] for c in analisis.CALIDADES] == ["★", "✓", "?!", "?", "??"]


def test_la_revision_coincide_y_reusa_lo_de_en_vivo(monkeypatch):
    tablero = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        tablero.push_san(san)
    jugadas = list(tablero.move_stack)
    # En vivo se analizó la primera jugada.
    en_vivo = {0: analizar_jugada(chess.Board(), jugadas[0], 0)}
    llamadas = []
    original = analisis.analizar_jugada
    monkeypatch.setattr(analisis, "analizar_jugada",
                        lambda *a, **k: llamadas.append(a[2]) or original(*a, **k))
    revision = revisar_partida(jugadas, chess.WHITE, previos=en_vivo)
    assert llamadas == [2]                     # solo analizó la que faltaba
    assert revision[0] is en_vivo[0]           # la de en vivo, tal cual
    # Y da lo mismo que analizar todo de cero.
    de_cero = revisar_partida(jugadas, chess.WHITE)
    assert [a["calidad"] for a in revision] == [a["calidad"] for a in de_cero]


# --- En la app -----------------------------------------------------------------------

@pytest.fixture(autouse=True)
def con_sesion_iniciada(google):
    google.entrar()


def abrir(fen=None):
    at = AppTest.from_file(RUTA_JUGAR, default_timeout=60).run()
    at.select_slider(key="nivel").set_value("Principiante").run()
    if fen:
        at.session_state.tablero = chess.Board(fen)
        at.run()
    return at


def argumentos(at):
    return json.loads(at.get("component_instance")[0].proto.json_args)


def test_iconito_sobre_tu_jugada():
    at = abrir()
    at.text_input(key="texto_jugada").input("e4").run()
    marca = argumentos(at)["marca"]
    assert marca["casilla"] == "e4"
    assert marca["simbolo"] in SIMBOLOS_CALIDAD.values()
    assert marca["tipo"] == at.session_state.analisis_vivo[0]["calidad"]
    # En el historial, al lado de tu jugada.
    assert f"e4{marca['simbolo']}" in at.text[0].value
    # Con la siguiente jugada tuya, el iconito pasa a la nueva casilla.
    jugada = next(m for m in at.session_state.tablero.legal_moves
                  if at.session_state.tablero.piece_at(m.from_square).piece_type == chess.KNIGHT)
    at.text_input(key="texto_jugada").input(jugada.uci()).run()
    assert argumentos(at)["marca"]["casilla"] == chess.square_name(jugada.to_square)


def test_error_grave_muestra_la_mejor_con_flecha():
    # Blancas regalan la dama (Qd5?? Rxd5).
    at = abrir("3rk3/8/8/8/8/8/3Q4/4K3 w - - 0 1")
    at.text_input(key="texto_jugada").input("Qd5").run()
    args = argumentos(at)
    assert args["marca"]["tipo"] == "error grave" and args["marca"]["simbolo"] == "??"
    mejor = at.session_state.analisis_vivo[0]["mejor_uci"]
    assert args["flecha"] == mejor
    assert "Error grave" in " ".join(c.value for c in at.caption)


def test_interruptor_apaga_todo():
    at = abrir()
    at.toggle(key="mostrar_calidad").set_value(False).run()
    at.text_input(key="texto_jugada").input("e4").run()
    assert argumentos(at)["marca"] is None
    assert at.session_state.analisis_vivo == {}       # ni siquiera analiza
    assert "★" not in at.text[0].value and "✓" not in at.text[0].value


def test_la_calidad_se_guarda_con_la_partida(carpeta_de_datos_temporal):
    at = abrir()
    at.text_input(key="texto_jugada").input("e4").run()
    at.button(key="abandonar").click().run()
    texto = (carpeta_de_datos_temporal / "partidas.pgn").read_text(encoding="utf-8")
    assert "[%calidad " in texto
    juego = chess.pgn.read_game(io.StringIO(texto))
    primera = next(iter(juego.mainline()))
    assert calidad_del_comentario(primera.comment) == at.session_state.analisis_vivo[0]["calidad"]


# --- PGN y tablas ----------------------------------------------------------------------

def test_calidad_en_el_pgn_y_en_las_tablas():
    tablero = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        tablero.push_san(san)
    pgn = armar_pgn(tablero, chess.WHITE, "Fácil", "Sin reloj",
                    calidades={0: "imprecisión", 2: "error grave"})
    juego = chess.pgn.read_game(io.StringIO(pgn))
    nodos = list(juego.mainline())
    assert nodos[0].nags == {6} and nodos[2].nags == {4}       # ?! y ?? estándar
    assert "[%calidad error_grave]" in nodos[2].comment
    _, jugadas = leer_pgn(pgn)
    # (pandas guarda los vacíos como NaN: los pasamos a None para comparar)
    calidades = [c if isinstance(c, str) else None for c in jugadas["calidad"]]
    assert calidades[:3] == ["imprecisión", None, "error grave"]


def test_calidad_del_comentario():
    assert calidad_del_comentario("[%eval 0.3] [%calidad mejor] [%clk 0:03:00]") == "mejor"
    assert calidad_del_comentario("[%calidad error_grave]") == "error grave"
    assert calidad_del_comentario("[%eval 0.3]") is None
    assert calidad_del_comentario(None) is None


# --- Tiempo del bot con reloj ------------------------------------------------------------

def test_el_bot_nunca_piensa_mas_de_lo_que_tiene():
    assert tiempo_para_el_bot(1.0, 180, 2) == 1.0          # le sobra: lo del nivel
    assert tiempo_para_el_bot(3.0, 10, 0) == 10 / 30        # poco: lo que le toca
    assert tiempo_para_el_bot(3.0, 0.5, 0) <= 0.25          # nunca más de la mitad
    assert tiempo_para_el_bot(3.0, 0.0, 0) == 0.01


def test_con_reloj_el_bot_no_pierde_por_tiempo():
    at = abrir()
    at.select_slider(key="nivel").set_value("Difícil").run()
    at.selectbox(key="control").set_value("3+2").run()
    at.session_state.tiempos = {chess.WHITE: 100.0, chess.BLACK: 0.6}
    at.session_state.reloj_de_los_tiempos = "3+2"
    at.run()
    at.text_input(key="texto_jugada").input("e4").run()     # primera: no gasta
    jugada = next(iter(at.session_state.tablero.legal_moves)).uci()
    at.text_input(key="texto_jugada").input(jugada).run()
    assert at.session_state.perdio_por_tiempo is None
    assert at.session_state.tiempos[chess.BLACK] > 0


# --- Elo combinado de medir_elo.py ------------------------------------------------------

def test_elo_combinado():
    elo, margen = elo_combinado([(1500, 1), (1500, 0)])
    assert round(elo) == 1500 and margen > 300               # 2 partidas: mucha duda
    elo, margen = elo_combinado([(1500, 1), (1700, 0.5), (1900, 0)] * 20)
    assert round(elo) == 1700 and margen < 100               # 60 partidas: menos duda
    elo, margen = elo_combinado([(1500, 1)] * 4)
    assert elo > 1700 and margen is None                     # ganó todo: es una cota


def test_profundidad_para_tiempo():
    assert profundidad_para_tiempo(1.0) == 2
    assert profundidad_para_tiempo(3.0) == 3
