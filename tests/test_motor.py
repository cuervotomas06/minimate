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


# --- Búsqueda de quietud ---------------------------------------------------

from src.motor import mejor_jugada, quietud  # noqa: E402
from src.evaluacion import evaluar  # noqa: E402


def test_quietud_evita_comer_un_peon_defendido_con_la_dama():
    # Qxd5 gana un peón... pero exd5 come la dama. Sin quietud, a profundidad 1
    # no lo ve (efecto horizonte); con quietud sí.
    tablero = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
    qxd5 = chess.Move.from_uci("d1d5")
    assert mejor_jugada(tablero, 1, con_quietud=False) == qxd5
    assert mejor_jugada(tablero, 1, con_quietud=True) != qxd5


def test_quietud_en_posicion_tranquila_es_la_evaluacion():
    # Sin capturas posibles, la quietud no cambia nada.
    import math
    tablero = chess.Board()
    assert quietud(tablero, -math.inf, math.inf) == evaluar(tablero)


def test_quietud_ve_la_captura_que_gana_material():
    # Blancas pueden comer una torre colgada: la quietud lo cuenta.
    import math
    tablero = chess.Board("4k3/8/8/3r4/8/8/8/3QK3 w - - 0 1")
    assert quietud(tablero, -math.inf, math.inf) > evaluar(tablero) + 400


def test_partida_real_ya_no_regala_la_dama():
    # Posición de la partida 1 contra Stockfish antes de 20. Qf3?? Bg4.
    jugadas_partida = ("Nf3 c6 Ng5 d5 Nc3 e5 d3 Nf6 Be3 d4 Nge4 dxc3 Bg5 Be7 Nxc3 O-O "
                       "e3 h6 Bh4 Ne8 Bg3 Bf6 Qf3 Nd7 Qf5 g6 Qg4 a5 e4 c5 Nd5 b5 O-O-O "
                       "Bg5+ Kb1 Nef6 Nxf6+ Nxf6").split()
    tablero = chess.Board()
    for san in jugadas_partida:
        tablero.push_san(san)
    assert tablero.san(mejor_jugada(tablero, 3)) != "Qf3"


# --- Repeticiones -----------------------------------------------------------

def test_ganando_no_repite_la_posicion():
    # Blancas tienen dama de más. En una posición limpia MiniMate elige Qd6
    # (d1d6). Armamos una historia donde Qd6 ya se jugó y se volvió atrás:
    # 1. Qd6 Kf7 2. Qd1 Ke8 -> estamos otra vez en la posición inicial.
    # Jugar Qd6 de nuevo repetiría una posición = empate (0), y blancas
    # van ganando: tiene que elegir otra jugada.
    tablero = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    assert mejor_jugada(tablero, 2) == chess.Move.from_uci("d1d6")

    for uci in ["d1d6", "e8f7", "d6d1", "f7e8"]:
        tablero.push_uci(uci)
    jugada = mejor_jugada(tablero, 2)
    assert jugada != chess.Move.from_uci("d1d6")

    # Y la jugada elegida no repite ninguna posición anterior.
    tablero.push(jugada)
    assert not tablero.is_repetition(2)


def test_repeticion_vale_cero_en_la_busqueda():
    # Después de 1. Qd6 Kf7 2. Qd1 Ke8 la posición está por segunda vez:
    # minimax la cuenta como empate aunque blancas tengan una dama de más.
    from src.motor import minimax
    tablero = chess.Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
    for uci in ["d1d6", "e8f7", "d6d1", "f7e8"]:
        tablero.push_uci(uci)
    assert minimax(tablero, 2) == 0
