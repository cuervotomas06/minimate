# Estima el Elo de cada nivel de MiniMate haciéndolos jugar entre ellos.
#
# Por qué hace falta: Stockfish no juega por debajo de UCI_Elo 1320, así que
# los niveles más débiles no se pueden medir contra él. En cambio:
#   1) medimos UN nivel contra Stockfish (medir_elo.py) -> ese es el "ancla";
#   2) cada nivel juega contra el siguiente y calculamos la DIFERENCIA de Elo;
#   3) encadenamos las diferencias a partir del ancla.
#
# MiniMate es determinista (misma posición -> misma jugada), así que dos
# niveles jugarían siempre la misma partida. Para variar, cada enfrentamiento
# arranca desde distintas aperturas, y cada apertura se juega con los dos colores.
#
# Uso:
#   python medir_niveles.py --ancla Difícil=1400
#   python medir_niveles.py --ancla Difícil=1400 --niveles Principiante Fácil Intermedio Difícil
#   python medir_niveles.py --help

import argparse
import math
import time
from datetime import date

import chess
import chess.pgn

from src.motor import mejor_jugada
from src.niveles import NIVELES

# Aperturas conocidas (pocas jugadas) para que las partidas no sean todas iguales.
APERTURAS = [
    "e4 e5 Nf3 Nc6",            # Abierta
    "e4 c5 Nf3 d6",             # Siciliana
    "d4 d5 c4 e6",              # Gambito de dama declinado
    "d4 Nf6 c4 g6",             # India de rey
    "e4 e6 d4 d5",              # Francesa
    "e4 c6 d4 d5",              # Caro-Kann
    "Nf3 d5 g3 Nf6",            # Réti
    "c4 e5 Nc3 Nf6",            # Inglesa
    "e4 e5 Nf3 Nc6 Bc4 Bc5",    # Italiana
    "d4 Nf6 c4 e6 Nc3 Bb4",     # Nimzo-india
]


def jugar(nivel_blancas, nivel_negras, apertura, max_jugadas):
    """Juega una partida entre dos niveles desde una apertura.
    Devuelve (resultado '1-0'/'0-1'/'1/2-1/2', motivo, tablero)."""
    tablero = chess.Board()
    for san in apertura.split():
        tablero.push_san(san)

    while not tablero.is_game_over(claim_draw=True):
        if tablero.fullmove_number > max_jugadas:
            return "1/2-1/2", f"tablas por límite de {max_jugadas} jugadas", tablero
        nivel = NIVELES[nivel_blancas if tablero.turn == chess.WHITE else nivel_negras]
        tablero.push(mejor_jugada(tablero, nivel["profundidad"], con_quietud=nivel["quietud"]))

    final = tablero.outcome(claim_draw=True)
    return final.result(), final.termination.name.lower().replace("_", " "), tablero


def diferencia_elo(puntos, partidas):
    """Cuánto Elo más tiene el que sacó 'puntos' de 'partidas'.
    Con 0% o 100% usamos media partida de corrección (es una cota)."""
    puntaje = puntos / partidas
    cota = ""
    if puntaje == 0:
        puntaje, cota = 0.5 / partidas, "<"
    elif puntaje == 1:
        puntaje, cota = (partidas - 0.5) / partidas, ">"
    return -400 * math.log10(1 / puntaje - 1), cota


def main():
    parser = argparse.ArgumentParser(description="Elo de los niveles de MiniMate jugando entre ellos.")
    parser.add_argument("--niveles", nargs="+", default=list(NIVELES),
                        help="niveles a comparar, del más débil al más fuerte")
    parser.add_argument("--ancla", required=True,
                        help="nivel con Elo conocido, por ejemplo: Difícil=1400")
    parser.add_argument("--aperturas", type=int, default=len(APERTURAS),
                        help=f"cuántas aperturas usar (cada una 2 partidas, máx {len(APERTURAS)})")
    parser.add_argument("--max-jugadas", type=int, default=150)
    parser.add_argument("--pgn", default="partidas_niveles.pgn")
    args = parser.parse_args()

    nombre_ancla, elo_ancla = args.ancla.split("=")
    elo_ancla = float(elo_ancla)
    if nombre_ancla not in args.niveles:
        parser.error(f"el ancla {nombre_ancla} tiene que estar en --niveles")
    for nombre in args.niveles:
        if nombre not in NIVELES:
            parser.error(f"no existe el nivel {nombre}. Opciones: {', '.join(NIVELES)}")

    aperturas = APERTURAS[:args.aperturas]
    diferencias = []  # diferencia de Elo entre cada par de niveles seguidos
    inicio_total = time.perf_counter()

    with open(args.pgn, "w", encoding="utf-8") as archivo_pgn:
        # Enfrentamos cada nivel con el siguiente: (0 vs 1), (1 vs 2), ...
        for debil, fuerte in zip(args.niveles, args.niveles[1:]):
            puntos_fuerte = 0.0
            partidas = 0
            for apertura in aperturas:
                for fuerte_con_blancas in (True, False):
                    blancas, negras = (fuerte, debil) if fuerte_con_blancas else (debil, fuerte)
                    inicio = time.perf_counter()
                    resultado, motivo, tablero = jugar(blancas, negras, apertura, args.max_jugadas)
                    partidas += 1
                    if resultado == "1/2-1/2":
                        puntos_fuerte += 0.5
                    elif (resultado == "1-0") == fuerte_con_blancas:
                        puntos_fuerte += 1

                    partida = chess.pgn.Game.from_board(tablero)
                    partida.headers.update({
                        "Event": f"Niveles MiniMate: {fuerte} vs {debil}",
                        "Date": date.today().strftime("%Y.%m.%d"),
                        "Round": str(partidas), "White": f"MiniMate {blancas}",
                        "Black": f"MiniMate {negras}", "Result": resultado,
                        "Termination": motivo, "Opening": apertura})
                    print(partida, file=archivo_pgn, end="\n\n")
                    archivo_pgn.flush()

                    print(f"{fuerte} vs {debil} | {partidas}/{2 * len(aperturas)} | "
                          f"{blancas} (blancas) {resultado} {negras} (negras) | {motivo} | "
                          f"{time.perf_counter() - inicio:.0f} s | "
                          f"{fuerte}: {puntos_fuerte}/{partidas}", flush=True)

            diferencia, cota = diferencia_elo(puntos_fuerte, partidas)
            diferencias.append((debil, fuerte, puntos_fuerte, partidas, diferencia, cota))
            print()

    # Encadenamos las diferencias a partir del ancla.
    elos = {nombre_ancla: elo_ancla}
    i_ancla = args.niveles.index(nombre_ancla)
    for i in range(i_ancla, len(args.niveles) - 1):          # hacia arriba
        _, fuerte, _, _, dif, _ = diferencias[i]
        elos[fuerte] = elos[args.niveles[i]] + dif
    for i in range(i_ancla - 1, -1, -1):                      # hacia abajo
        debil, _, _, _, dif, _ = diferencias[i]
        elos[debil] = elos[args.niveles[i + 1]] - dif

    print(f"{'Enfrentamiento':<28} {'Puntos del fuerte':>18} {'Diferencia':>11}")
    print("-" * 59)
    for debil, fuerte, puntos, partidas, dif, cota in diferencias:
        print(f"{fuerte + ' vs ' + debil:<28} {f'{puntos}/{partidas}':>18} {cota + f'{dif:+.0f}':>11}")

    print(f"\n{'Nivel':<14} {'Elo estimado':>12}")
    print("-" * 27)
    for nombre in args.niveles:
        marca = "  (ancla)" if nombre == nombre_ancla else ""
        print(f"{nombre:<14} {elos[nombre]:>12.0f}{marca}")
    print(f"\nTiempo total: {(time.perf_counter() - inicio_total) / 60:.1f} min. "
          f"Partidas en {args.pgn}")
    print("'<' y '>' = un nivel ganó o perdió todo: la diferencia real puede ser mayor.")


if __name__ == "__main__":
    main()
