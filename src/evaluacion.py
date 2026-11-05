# Evaluación de posiciones para MiniMate.
# La idea: darle un número a una posición. Positivo = mejor para blancas,
# negativo = mejor para negras. Se mide en centipeones (100 = un peón).

import chess
from src.tablas import TABLAS

# Valor de cada tipo de pieza en centipeones.
# El rey vale 0 porque nunca se captura: su "valor" se maneja con el mate.
VALORES = {
    chess.PAWN: 100,    # peón
    chess.KNIGHT: 320,  # caballo
    chess.BISHOP: 330,  # alfil
    chess.ROOK: 500,    # torre
    chess.QUEEN: 900,   # dama
    chess.KING: 0,      # rey
}

# Puntaje que usamos para el jaque mate (mucho más que todo el material junto).
VALOR_MATE = 100000


from src.tablas import TABLAS

def evaluar(board):
    if board.is_checkmate():
        return -100000 if board.turn == chess.WHITE else 100000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    puntaje = 0
    for casilla, pieza in board.piece_map().items():
        tabla = TABLAS[pieza.piece_type]
        valor = VALORES[pieza.piece_type]
        if pieza.color == chess.WHITE:
            # la librería numera a1=0 ... h8=63; las tablas arrancan en a8,
            # así que para blancas hay que espejar la fila
            puntaje += valor + tabla[chess.square_mirror(casilla)]
        else:
            # para negras el tablero ya está "dado vuelta"
            puntaje -= valor + tabla[casilla]
    return puntaje