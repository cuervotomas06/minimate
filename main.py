import chess
from src.motor import mejor_jugada

board = chess.Board()

while not board.is_game_over():
    print(board, "\n")

    if board.turn == chess.WHITE:
        texto = input("Tu jugada (ej: e2e4): ")
        try:
            jugada = chess.Move.from_uci(texto)
        except ValueError:
            print("Formato inválido.\n")
            continue
        if jugada not in board.legal_moves:
            print("Jugada ilegal.\n")
            continue
        board.push(jugada)
    else:
        print("MiniMate está pensando...")
        jugada = mejor_jugada(board, profundidad=3)
        print("MiniMate juega:", jugada, "\n")
        board.push(jugada)

print(board)
print("Resultado:", board.result())