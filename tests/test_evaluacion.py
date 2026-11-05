# Tests de la función evaluar. Se corren con: pytest

import chess

from src.evaluacion import evaluar


def test_posicion_inicial_da_cero():
    # Al empezar, los dos bandos tienen el mismo material.
    tablero = chess.Board()
    assert evaluar(tablero) == 0


def test_sin_dama_negra_da_900():
    # Igual que la inicial pero sin la dama negra: blancas tienen 900 de más.
    tablero = chess.Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert evaluar(tablero) == 900


def test_mate_del_pastor():
    # Mate del pastor: le toca mover a negras y están en mate,
    # así que ganan blancas y debe dar 100000.
    tablero = chess.Board("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")
    assert tablero.is_checkmate()  # chequeo de que el FEN es realmente mate
    assert evaluar(tablero) == 100000
