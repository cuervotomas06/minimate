# Tests del ordenamiento de jugadas. Se corren con: pytest

import chess

from src.motor import puntaje_jugada, ordenar_jugadas


def test_captura_mvv_lva():
    # Un peón blanco en e4 puede capturar una dama en d5: 10*900 - 100 = 8900.
    tablero = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    jugada = chess.Move.from_uci("e4d5")
    assert puntaje_jugada(tablero, jugada) == 8900


def test_captura_al_paso():
    # Negras acaban de jugar d7d5; el peón de e5 captura al paso en d6.
    # La casilla destino está vacía, pero la víctima es un peón: 10*100 - 100 = 900.
    tablero = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    jugada = chess.Move.from_uci("e5d6")
    assert tablero.is_en_passant(jugada)
    assert puntaje_jugada(tablero, jugada) == 900


def test_promocion_suma_valor_de_la_pieza():
    # Peón en a7 corona en a8 (sin captura ni jaque): suma el valor de la dama.
    # (el rey negro está en h7 para que la dama nueva no le dé jaque)
    tablero = chess.Board("8/P6k/8/8/8/8/8/4K3 w - - 0 1")
    jugada = chess.Move.from_uci("a7a8q")
    assert puntaje_jugada(tablero, jugada) == 900


def test_ordenar_pone_la_captura_primero():
    tablero = chess.Board("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1")
    jugadas = ordenar_jugadas(tablero)
    assert jugadas[0] == chess.Move.from_uci("e4d5")
    # Y no se pierde ni se agrega ninguna jugada legal.
    assert set(jugadas) == set(tablero.legal_moves)
