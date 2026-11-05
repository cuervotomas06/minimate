import math
import chess
from src.evaluacion import evaluar, VALORES

# Contador global: cuántas posiciones evaluó minimax (llamadas a evaluar).
# Sirve para comparar cuánto trabajo ahorra ordenar las jugadas.
# Para reiniciarlo desde otro archivo: motor.posiciones_evaluadas = 0
posiciones_evaluadas = 0

# Puntos extra que le damos a una jugada que da jaque.
BONUS_JAQUE = 50


def puntaje_jugada(board, jugada):
    """Puntaje "a ojo" de una jugada, para decidir cuál mirar primero.
    No es la evaluación real: solo sirve para ordenar. Más alto = más prometedora."""
    puntaje = 0

    # Capturas con MVV-LVA ("víctima más valiosa, atacante menos valioso"):
    # conviene mirar primero capturar una dama con un peón que un peón con una dama.
    if board.is_capture(jugada):
        if board.is_en_passant(jugada):
            # En la captura al paso la casilla destino está vacía:
            # la víctima siempre es un peón.
            victima = chess.PAWN
        else:
            victima = board.piece_at(jugada.to_square).piece_type
        atacante = board.piece_at(jugada.from_square).piece_type
        puntaje += 10 * VALORES[victima] - VALORES[atacante]

    # Promociones: sumamos el valor de la pieza nueva (casi siempre dama).
    if jugada.promotion is not None:
        puntaje += VALORES[jugada.promotion]

    # Jaques: un pequeño bonus.
    if board.gives_check(jugada):
        puntaje += BONUS_JAQUE

    return puntaje


def ordenar_jugadas(board):
    """Devuelve las jugadas legales ordenadas de mayor a menor puntaje."""
    jugadas = list(board.legal_moves)
    # key=...: para cada jugada calcula su puntaje y ordena por ese número.
    # reverse=True: de mayor a menor.
    jugadas.sort(key=lambda jugada: puntaje_jugada(board, jugada), reverse=True)
    return jugadas


def minimax(board, profundidad, alfa=-math.inf, beta=math.inf, ordenar=True):
    """Minimax con poda alfa-beta.
    alfa: lo mejor que blancas ya tienen asegurado.
    beta: lo mejor que negras ya tienen asegurado.
    ordenar: si es True, mira primero las jugadas más prometedoras
    (así la poda corta antes)."""
    # "global" hace falta para poder MODIFICAR la variable del módulo
    # desde adentro de la función (leerla no lo necesita).
    global posiciones_evaluadas

    if profundidad == 0 or board.is_game_over():
        posiciones_evaluadas += 1
        return evaluar(board)

    # Elegimos en qué orden recorrer las jugadas.
    jugadas = ordenar_jugadas(board) if ordenar else board.legal_moves

    if board.turn == chess.WHITE:
        mejor = -math.inf
        for jugada in jugadas:
            board.push(jugada)
            valor = minimax(board, profundidad - 1, alfa, beta, ordenar)
            board.pop()
            mejor = max(mejor, valor)
            alfa = max(alfa, mejor)
            if alfa >= beta:
                break          # poda: negras nunca dejarían llegar acá
        return mejor
    else:
        mejor = math.inf
        for jugada in jugadas:
            board.push(jugada)
            valor = minimax(board, profundidad - 1, alfa, beta, ordenar)
            board.pop()
            mejor = min(mejor, valor)
            beta = min(beta, mejor)
            if alfa >= beta:
                break          # poda: blancas nunca dejarían llegar acá
        return mejor


def mejor_jugada(board, profundidad=3, ordenar=True):
    juegan_blancas = board.turn == chess.WHITE
    mejor_valor = -math.inf if juegan_blancas else math.inf
    elegida = None
    alfa, beta = -math.inf, math.inf

    jugadas = ordenar_jugadas(board) if ordenar else board.legal_moves

    for jugada in jugadas:
        board.push(jugada)
        valor = minimax(board, profundidad - 1, alfa, beta, ordenar)
        board.pop()

        if juegan_blancas and valor > mejor_valor:
            mejor_valor, elegida = valor, jugada
            alfa = max(alfa, valor)
        elif not juegan_blancas and valor < mejor_valor:
            mejor_valor, elegida = valor, jugada
            beta = min(beta, valor)

    return elegida
