# Evaluación "avanzada": la de src/evaluacion.py más lo que hace falta para
# jugar bien los finales. (evaluacion.py queda igual: es la de siempre.)
#
# Qué agrega:
# 1. Evaluación "graduada" (tapered eval): en el medio juego el rey tiene que
#    esconderse, pero en el final tiene que ir al centro a pelear. Calculamos
#    dos evaluaciones (medio juego y final) y las mezclamos según cuánto
#    material queda: con todas las piezas cuenta la de medio juego, sin piezas
#    (solo reyes y peones) cuenta la de final.
# 2. Peones pasados: un peón sin peones rivales adelante (ni en las columnas
#    de al lado) puede coronar. Vale más cuanto más avanzado, y más en el final.
# 3. Pareja de alfiles: los dos alfiles juntos valen un poco más que la suma.
# 4. Finales ganados (por ejemplo rey y torre contra rey): empujar al rey
#    rival al borde y acercar el propio. Sin esto el motor "ve" que gana pero
#    no sabe cómo dar el mate y da vueltas.
#
# Igual que evaluar(): centipeones desde el punto de vista de blancas. No
# detecta mates ni tablas: de eso se encarga la búsqueda.

import chess

from src.evaluacion import VALORES
from src.tablas import TABLAS

# Tablas para el FINAL (las de medio juego son las de src/tablas.py).
# Mismo formato: la primera fila es la octava, vistas desde blancas.
REY_FINAL = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -30, -20, -10,   0,   0, -10, -20, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -30,   0,   0,   0,   0, -30, -30,
    -50, -30, -30, -30, -30, -30, -30, -50,
]
PEON_FINAL = [
      0,   0,   0,   0,   0,   0,   0,   0,
     80,  80,  80,  80,  80,  80,  80,  80,
     50,  50,  50,  50,  50,  50,  50,  50,
     30,  30,  30,  30,  30,  30,  30,  30,
     20,  20,  20,  20,  20,  20,  20,  20,
     10,  10,  10,  10,  10,  10,  10,  10,
      5,   5,   5,   5,   5,   5,   5,   5,
      0,   0,   0,   0,   0,   0,   0,   0,
]
TABLAS_FINAL = {**TABLAS, chess.KING: REY_FINAL, chess.PAWN: PEON_FINAL}

# Cuánto "pesa" cada pieza para saber en qué fase estamos (24 = todas).
FASE_PIEZA = {chess.KNIGHT: 1, chess.BISHOP: 1, chess.ROOK: 2, chess.QUEEN: 4}
FASE_TOTAL = 24

# Peón pasado, según cuántas filas avanzó (0 = su fila inicial... 7).
PASADO_MEDIO = [0, 5, 10, 15, 25, 40, 60, 0]
PASADO_FINAL = [0, 10, 20, 35, 60, 90, 130, 0]

PAREJA_ALFILES = (30, 50)   # (medio juego, final)


def _mascaras_de_peon_pasado():
    """Para cada color y casilla: las casillas de adelante (en su columna y
    las dos de al lado). Si ahí no hay peones rivales, el peón es pasado."""
    mascaras = {chess.WHITE: [0] * 64, chess.BLACK: [0] * 64}
    for casilla in chess.SQUARES:
        columna, fila = chess.square_file(casilla), chess.square_rank(casilla)
        columnas = [c for c in (columna - 1, columna, columna + 1) if 0 <= c <= 7]
        for color, filas in ((chess.WHITE, range(fila + 1, 8)), (chess.BLACK, range(0, fila))):
            mascara = 0
            for f in filas:
                for c in columnas:
                    mascara |= chess.BB_SQUARES[chess.square(c, f)]
            mascaras[color][casilla] = mascara
    return mascaras


MASCARA_PASADO = _mascaras_de_peon_pasado()


def fase_de_juego(board):
    """De 0 (solo reyes y peones) a 24 (todas las piezas)."""
    fase = 0
    for tipo, peso in FASE_PIEZA.items():
        fase += peso * (len(board.pieces(tipo, chess.WHITE)) + len(board.pieces(tipo, chess.BLACK)))
    return min(fase, FASE_TOTAL)


def distancia_al_centro(casilla):
    """0 en las cuatro casillas del centro, 6 en las esquinas."""
    columna, fila = chess.square_file(casilla), chess.square_rank(casilla)
    return max(3 - columna, columna - 4) + max(3 - fila, fila - 4)


def distancia_entre(a, b):
    """Distancia "manhattan" entre dos casillas (de 0 a 14)."""
    return (abs(chess.square_file(a) - chess.square_file(b))
            + abs(chess.square_rank(a) - chess.square_rank(b)))


def evaluar_avanzada(board):
    medio = final = 0
    for casilla, pieza in board.piece_map().items():
        tipo = pieza.piece_type
        # Las tablas están vistas desde blancas: para blancas se espeja la fila.
        indice = chess.square_mirror(casilla) if pieza.color == chess.WHITE else casilla
        signo = 1 if pieza.color == chess.WHITE else -1
        medio += signo * (VALORES[tipo] + TABLAS[tipo][indice])
        final += signo * (VALORES[tipo] + TABLAS_FINAL[tipo][indice])

    # Peones pasados.
    for color, signo in ((chess.WHITE, 1), (chess.BLACK, -1)):
        peones_rivales = board.pieces_mask(chess.PAWN, not color)
        for casilla in board.pieces(chess.PAWN, color):
            if not MASCARA_PASADO[color][casilla] & peones_rivales:
                fila = chess.square_rank(casilla)
                avance = fila if color == chess.WHITE else 7 - fila
                medio += signo * PASADO_MEDIO[avance]
                final += signo * PASADO_FINAL[avance]

    # Pareja de alfiles.
    for color, signo in ((chess.WHITE, 1), (chess.BLACK, -1)):
        if len(board.pieces(chess.BISHOP, color)) >= 2:
            medio += signo * PAREJA_ALFILES[0]
            final += signo * PAREJA_ALFILES[1]

    # Mezcla según la fase.
    fase = fase_de_juego(board)
    # round (y no //): // redondea siempre para abajo, y una posición daría
    # +1097 para blancas pero -1098 para negras. round es simétrico.
    total = round((medio * fase + final * (FASE_TOTAL - fase)) / FASE_TOTAL)
    return total + empujar_al_borde(board, total, fase)


def empujar_al_borde(board, total, fase):
    """En un final claramente ganado contra un rival sin peones: puntos por
    arrinconar al rey rival y por acercar el propio (así se da el mate)."""
    if fase > 6 or abs(total) < 300:
        return 0
    ganador = chess.WHITE if total > 0 else chess.BLACK
    perdedor = not ganador
    if board.pieces_mask(chess.PAWN, perdedor):
        return 0
    rey_ganador, rey_perdedor = board.king(ganador), board.king(perdedor)
    if rey_ganador is None or rey_perdedor is None:
        return 0
    bonus = 10 * distancia_al_centro(rey_perdedor) + 4 * (14 - distancia_entre(rey_ganador, rey_perdedor))
    return bonus if ganador == chess.WHITE else -bonus
