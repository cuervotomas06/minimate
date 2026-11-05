import math
import chess
from src.evaluacion import evaluar


def minimax(board, profundidad, alfa=-math.inf, beta=math.inf):
    """Minimax con poda alfa-beta.
    alfa: lo mejor que blancas ya tienen asegurado.
    beta: lo mejor que negras ya tienen asegurado."""

    if profundidad == 0 or board.is_game_over():
        return evaluar(board)

    if board.turn == chess.WHITE:
        mejor = -math.inf
        for jugada in board.legal_moves:
            board.push(jugada)
            valor = minimax(board, profundidad - 1, alfa, beta)
            board.pop()
            mejor = max(mejor, valor)
            alfa = max(alfa, mejor)
            if alfa >= beta:
                break          # poda: negras nunca dejarían llegar acá
        return mejor
    else:
        mejor = math.inf
        for jugada in board.legal_moves:
            board.push(jugada)
            valor = minimax(board, profundidad - 1, alfa, beta)
            board.pop()
            mejor = min(mejor, valor)
            beta = min(beta, mejor)
            if alfa >= beta:
                break          # poda: blancas nunca dejarían llegar acá
        return mejor


def mejor_jugada(board, profundidad=3):
    juegan_blancas = board.turn == chess.WHITE
    mejor_valor = -math.inf if juegan_blancas else math.inf
    elegida = None
    alfa, beta = -math.inf, math.inf

    for jugada in board.legal_moves:
        board.push(jugada)
        valor = minimax(board, profundidad - 1, alfa, beta)
        board.pop()

        if juegan_blancas and valor > mejor_valor:
            mejor_valor, elegida = valor, jugada
            alfa = max(alfa, valor)
        elif not juegan_blancas and valor < mejor_valor:
            mejor_valor, elegida = valor, jugada
            beta = min(beta, valor)

    return elegida