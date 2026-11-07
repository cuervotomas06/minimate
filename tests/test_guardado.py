# Tests de src/guardado.py: PGN de la partida y guardado en datos/partidas.pgn.
# Se corren con: pytest

import io
from datetime import datetime

import chess
import chess.pgn

from src.analisis import evaluaciones_de_la_revision, revisar_partida
from src.evaluacion import VALOR_MATE
from src.guardado import (armar_pgn, guardar_partida, nombre_de_archivo,
                          resultado_y_terminacion, time_control)

FECHA = datetime(2026, 11, 6, 15, 30, 0)


def tablero_con(jugadas_san, fen=None):
    tablero = chess.Board(fen) if fen else chess.Board()
    for san in jugadas_san.split():
        tablero.push_san(san)
    return tablero


def leer(pgn):
    return chess.pgn.read_game(io.StringIO(pgn))


# --- Resultado y terminación ---------------------------------------------------

def test_mate():
    tablero = tablero_con("f3 e5 g4 Qh4#")
    assert resultado_y_terminacion(tablero, chess.WHITE) == ("0-1", "Normal", "jaque mate")


def test_ahogado():
    tablero = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert resultado_y_terminacion(tablero, chess.WHITE) == ("1/2-1/2", "Normal", "ahogado")


def test_tiempo():
    tablero = tablero_con("e4 e5")
    assert resultado_y_terminacion(tablero, chess.WHITE, perdio_por_tiempo=chess.WHITE) == \
        ("0-1", "Time forfeit", "tiempo")
    # Al que le queda tiempo solo tiene el rey: tablas.
    solo_rey = chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    assert resultado_y_terminacion(solo_rey, chess.WHITE, perdio_por_tiempo=chess.WHITE)[0] == "1/2-1/2"


def test_abandono():
    tablero = tablero_con("e4 e5")
    assert resultado_y_terminacion(tablero, chess.BLACK, abandono=True) == \
        ("1-0", "Abandoned", "abandono")


def test_sin_terminar():
    assert resultado_y_terminacion(tablero_con("e4"), chess.WHITE)[0] == "*"


# --- PGN -------------------------------------------------------------------------

def test_encabezados():
    pgn = armar_pgn(tablero_con("f3 e5 g4 Qh4#"), chess.WHITE, "Difícil", "3+2", fecha=FECHA)
    encabezados = leer(pgn).headers
    assert encabezados["Date"] == "2026.11.06"
    assert encabezados["Time"] == "15:30:00"
    assert encabezados["White"] == "Vos"
    assert encabezados["Black"] == "MiniMate (Difícil)"
    assert encabezados["Result"] == "0-1"
    assert encabezados["TimeControl"] == "180+2"
    assert encabezados["Termination"] == "Normal"
    assert encabezados["MiColor"] == "blancas"
    assert encabezados["Nivel"] == "Difícil"
    assert encabezados["Reloj"] == "3+2"
    assert encabezados["Terminacion"] == "jaque mate"
    assert encabezados["Origen"] == "minimate"


def test_con_negras():
    pgn = armar_pgn(tablero_con("e4 e5"), chess.BLACK, "Fácil", "Sin reloj",
                    abandono=True, fecha=FECHA)
    encabezados = leer(pgn).headers
    assert encabezados["White"] == "MiniMate (Fácil)" and encabezados["Black"] == "Vos"
    assert encabezados["Result"] == "1-0"
    assert encabezados["TimeControl"] == "-"
    assert encabezados["Terminacion"] == "abandono"


def test_reloj_y_evaluacion_por_jugada():
    # Formato de Lichess: { [%eval 0.35] [%clk 0:02:58] } después de cada jugada.
    tablero = tablero_con("f3 e5 g4 Qh4#")
    revision = revisar_partida(tablero.move_stack, chess.WHITE)
    evaluaciones = evaluaciones_de_la_revision(revision, list(tablero.move_stack))
    pgn = armar_pgn(tablero, chess.WHITE, "Intermedio", "3+2",
                    relojes=[180, 180, 178.5, 179.2], evaluaciones=evaluaciones, fecha=FECHA)
    assert "[%clk 0:02:58.5]" in pgn
    assert "[%eval #-1]" in pgn            # después de g4??: negras dan mate en 1
    juego = leer(pgn)
    nodos = list(juego.mainline())
    assert [n.clock() for n in nodos] == [180, 180, 178.5, 179.2]
    assert nodos[0].eval().white().score() == evaluaciones[1]
    assert nodos[3].eval() is None          # en la posición de mate no hace falta
    assert juego.eval() is not None         # evaluación de la posición inicial
    # Y las jugadas se leen igual.
    assert [n.move for n in nodos] == list(tablero.move_stack)


def test_sin_reloj_no_hay_clk():
    pgn = armar_pgn(tablero_con("e4 e5"), chess.WHITE, "Fácil", "Sin reloj",
                    relojes=[None, None], fecha=FECHA)
    assert "%clk" not in pgn


def test_time_control():
    assert time_control("5+3") == "300+3"
    assert time_control("Sin reloj") == "-"


def test_mate_en_el_pgn():
    from src.guardado import puntaje_lichess
    assert str(puntaje_lichess(VALOR_MATE - 5).white()) == "#+3"
    assert str(puntaje_lichess(-(VALOR_MATE - 1)).white()) == "#-1"
    assert str(puntaje_lichess(35).white()) == "+35"


# --- Guardar en el archivo -----------------------------------------------------

def test_guardar_agrega_al_final(carpeta_de_datos_temporal):
    primera = armar_pgn(tablero_con("e4 e5"), chess.WHITE, "Fácil", "Sin reloj",
                        abandono=True, fecha=FECHA)
    segunda = armar_pgn(tablero_con("f3 e5 g4 Qh4#"), chess.WHITE, "Fácil", "Sin reloj",
                        fecha=FECHA)
    ruta = guardar_partida(primera)
    guardar_partida(segunda)
    assert ruta == carpeta_de_datos_temporal / "partidas.pgn"   # nunca en datos/ de verdad
    lector = io.StringIO(ruta.read_text(encoding="utf-8"))
    juegos = []
    while (juego := chess.pgn.read_game(lector)) is not None:
        juegos.append(juego)
    assert [j.headers["Terminacion"] for j in juegos] == ["abandono", "jaque mate"]


def test_nombre_de_archivo():
    assert nombre_de_archivo(FECHA) == "minimate_2026-11-06_1530.pgn"
