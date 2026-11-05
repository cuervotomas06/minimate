# Tests de la parte Python del componente (src/componente_tablero).
# Se corren con: pytest

import base64

import chess

from src.componente_tablero import PIEZAS, procesar_valor


def test_doce_piezas_como_data_uri_svg():
    assert sorted(PIEZAS) == sorted(
        c + p for c in "wb" for p in "PNBRQK")
    prefijo = "data:image/svg+xml;base64,"
    for uri in PIEZAS.values():
        assert uri.startswith(prefijo)
        svg = base64.b64decode(uri[len(prefijo):]).decode("utf-8")
        assert svg.startswith("<svg")


def valor(uci, tablero, id_jugada="x"):
    return {"uci": uci, "fen": tablero.fen(), "id": id_jugada}


def test_jugada_valida():
    tablero = chess.Board()
    nuevo_id, jugada, error = procesar_valor(tablero, valor("e2e4", tablero), None, chess.WHITE)
    assert (nuevo_id, jugada, error) == ("x", chess.Move.from_uci("e2e4"), None)


def test_mismo_id_se_ignora():
    tablero = chess.Board()
    resultado = procesar_valor(tablero, valor("e2e4", tablero), "x", chess.WHITE)
    assert resultado == ("x", None, None)


def test_sin_valor_no_hace_nada():
    tablero = chess.Board()
    assert procesar_valor(tablero, None, "viejo", chess.WHITE) == ("viejo", None, None)


def test_fen_desactualizado():
    tablero = chess.Board()
    v = valor("e2e4", tablero)
    tablero.push_san("Nf3")  # la posición cambió después de que el JS jugó
    _, jugada, error = procesar_valor(tablero, v, None, chess.BLACK)
    assert jugada is None and "desactualizado" in error


def test_no_es_mi_turno():
    tablero = chess.Board()
    _, jugada, error = procesar_valor(tablero, valor("e2e4", tablero), None, chess.BLACK)
    assert jugada is None and "turno" in error


def test_ilegal_y_basura():
    tablero = chess.Board()
    _, jugada, error = procesar_valor(tablero, valor("e2e5", tablero), None, chess.WHITE)
    assert jugada is None and "ilegal" in error
    _, jugada, error = procesar_valor(tablero, valor("hola", tablero, "y"), None, chess.WHITE)
    assert jugada is None and "no entiendo" in error
