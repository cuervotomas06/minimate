# Estima el Elo de MiniMate haciéndolo jugar contra Stockfish con fuerza limitada.
#
# Uso (desde la raíz del proyecto, con el venv activo):
#   python medir_elo.py                              # 10 partidas a 1320, 1500 y 1700
#   python medir_elo.py --partidas 2 --niveles 1320  # prueba rápida
#   python medir_elo.py --profundidad 2 --tiempo 0.05
#   python medir_elo.py --help                       # todas las opciones
#
# Stockfish tiene que estar en la carpeta motores/ (cualquier .exe ahí adentro).
# Las partidas se guardan en un .pgn para revisarlas con cualquier programa de ajedrez.

import argparse
import math
import sys
import time
from datetime import date
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from src.motor import mejor_jugada

CARPETA_MOTORES = Path(__file__).parent / "motores"


# ---------------------------------------------------------------------------
# Stockfish
# ---------------------------------------------------------------------------

def buscar_stockfish():
    """Busca un .exe en motores/ (prefiere uno que se llame 'stockfish...')."""
    ejecutables = sorted(CARPETA_MOTORES.rglob("*.exe"))
    if not ejecutables:
        sys.exit(f"No encontré ningún .exe en {CARPETA_MOTORES}.\n"
                 "Descargá Stockfish de https://stockfishchess.org/download/ "
                 "y poné el ejecutable en esa carpeta (o usá --motor RUTA).")
    con_nombre = [e for e in ejecutables if "stockfish" in e.name.lower()]
    return (con_nombre or ejecutables)[0]


def configurar_nivel(motor, elo):
    """Limita la fuerza de Stockfish a 'elo' (UCI_Elo)."""
    opcion = motor.options["UCI_Elo"]
    if not opcion.min <= elo <= opcion.max:
        sys.exit(f"Este Stockfish acepta UCI_Elo entre {opcion.min} y {opcion.max}; "
                 f"pediste {elo}.")
    motor.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})


# ---------------------------------------------------------------------------
# Una partida
# ---------------------------------------------------------------------------

def jugar_partida(motor, elo, minimate_blancas, profundidad, tiempo, max_jugadas,
                  con_quietud=True):
    """Juega una partida completa.
    Devuelve (puntos de MiniMate: 1, 0.5 o 0, resultado '1-0'/..., motivo, tablero)."""
    tablero = chess.Board()
    limite = chess.engine.Limit(time=tiempo)

    # claim_draw=True: también termina por triple repetición y regla de 50 jugadas
    # (si no, dos motores pueden repetir posiciones para siempre).
    while not tablero.is_game_over(claim_draw=True):
        # "Jugadas" completas: una de blancas + una de negras.
        if tablero.fullmove_number > max_jugadas:
            return 0.5, "1/2-1/2", f"tablas por límite de {max_jugadas} jugadas", tablero

        turno_de_minimate = (tablero.turn == chess.WHITE) == minimate_blancas
        if turno_de_minimate:
            jugada = mejor_jugada(tablero, profundidad, con_quietud=con_quietud)
        else:
            jugada = motor.play(tablero, limite).move
        tablero.push(jugada)

    final = tablero.outcome(claim_draw=True)
    motivos = {
        chess.Termination.CHECKMATE: "jaque mate",
        chess.Termination.STALEMATE: "ahogado",
        chess.Termination.INSUFFICIENT_MATERIAL: "material insuficiente",
        chess.Termination.THREEFOLD_REPETITION: "triple repetición",
        chess.Termination.FIFTY_MOVES: "regla de 50 jugadas",
        chess.Termination.FIVEFOLD_REPETITION: "quíntuple repetición",
        chess.Termination.SEVENTYFIVE_MOVES: "regla de 75 jugadas",
    }
    motivo = motivos.get(final.termination, final.termination.name)

    if final.winner is None:
        puntos = 0.5
    elif (final.winner == chess.WHITE) == minimate_blancas:
        puntos = 1.0
    else:
        puntos = 0.0
    return puntos, final.result(), motivo, tablero


def a_pgn(tablero, resultado, motivo, elo, minimate_blancas, nombre_minimate, ronda):
    """Convierte la partida en un objeto PGN con encabezados."""
    partida = chess.pgn.Game.from_board(tablero)
    nombre_stockfish = f"Stockfish (UCI_Elo {elo})"
    partida.headers["Event"] = f"MiniMate vs Stockfish {elo}"
    partida.headers["Date"] = date.today().strftime("%Y.%m.%d")
    partida.headers["Round"] = str(ronda)
    partida.headers["White"] = nombre_minimate if minimate_blancas else nombre_stockfish
    partida.headers["Black"] = nombre_stockfish if minimate_blancas else nombre_minimate
    partida.headers["Result"] = resultado
    partida.headers["Termination"] = motivo
    return partida


# ---------------------------------------------------------------------------
# Elo
# ---------------------------------------------------------------------------

def estimar_elo(elo_rival, puntos, partidas):
    """Elo estimado con  Elo_rival - 400 * log10(1 / puntaje - 1).

    Con 0% o 100% la fórmula da infinito, así que usamos media partida de
    corrección (como si hubiera sacado 0.5 puntos más, o 0.5 menos) y lo
    marcamos con '<' o '>': es una cota, no un valor exacto.
    Devuelve (texto para mostrar, número)."""
    puntaje = puntos / partidas
    signo = ""
    if puntaje == 0:
        puntaje, signo = 0.5 / partidas, "< "
    elif puntaje == 1:
        puntaje, signo = (partidas - 0.5) / partidas, "> "
    elo = elo_rival - 400 * math.log10(1 / puntaje - 1)
    return f"{signo}{elo:.0f}", elo


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------

def leer_argumentos():
    parser = argparse.ArgumentParser(
        description="Estima el Elo de MiniMate jugando contra Stockfish limitado.")
    parser.add_argument("--profundidad", type=int, default=3,
                        help="profundidad de búsqueda de MiniMate (por defecto 3)")
    parser.add_argument("--partidas", type=int, default=10,
                        help="partidas por nivel, alternando colores (por defecto 10)")
    parser.add_argument("--niveles", type=int, nargs="+", default=[1320, 1500, 1700],
                        help="UCI_Elo de Stockfish a probar (por defecto 1320 1500 1700)")
    parser.add_argument("--sin-quietud", action="store_true",
                        help="apaga la búsqueda de quietud de MiniMate (para comparar)")
    parser.add_argument("--tiempo", type=float, default=0.1,
                        help="segundos por jugada para Stockfish (por defecto 0.1)")
    parser.add_argument("--max-jugadas", type=int, default=150,
                        help="pasadas estas jugadas, la partida es tablas (por defecto 150)")
    parser.add_argument("--pgn", default="partidas_elo.pgn",
                        help="archivo donde guardar las partidas (por defecto partidas_elo.pgn)")
    parser.add_argument("--motor", type=Path, default=None,
                        help="ruta al ejecutable de Stockfish (por defecto, el .exe de motores/)")
    return parser.parse_args()


def main():
    args = leer_argumentos()
    ruta_motor = args.motor or buscar_stockfish()
    con_quietud = not args.sin_quietud
    nombre_minimate = (f"MiniMate (prof. {args.profundidad}, "
                       f"{'con' if con_quietud else 'sin'} quietud)")
    print(f"Motor: {ruta_motor}")
    print(f"{nombre_minimate} | {args.partidas} partidas por nivel | "
          f"niveles {args.niveles} | Stockfish {args.tiempo} s por jugada\n")

    resumen = []  # una fila por nivel
    inicio_total = time.perf_counter()

    # "with" cierra Stockfish y el archivo aunque algo falle o cortes con Ctrl+C.
    with chess.engine.SimpleEngine.popen_uci(str(ruta_motor)) as motor, \
            open(args.pgn, "w", encoding="utf-8") as archivo_pgn:
        # Un solo hilo y poca memoria: así todas las partidas son comparables.
        motor.configure({"Threads": 1, "Hash": 16})

        for elo in args.niveles:
            configurar_nivel(motor, elo)
            ganadas = empatadas = perdidas = 0

            for i in range(args.partidas):
                minimate_blancas = i % 2 == 0  # alternamos colores
                inicio = time.perf_counter()
                puntos, resultado, motivo, tablero = jugar_partida(
                    motor, elo, minimate_blancas, args.profundidad,
                    args.tiempo, args.max_jugadas, con_quietud)
                segundos = time.perf_counter() - inicio

                if puntos == 1:
                    ganadas += 1
                    letra = "GANÓ "
                elif puntos == 0.5:
                    empatadas += 1
                    letra = "EMPATÓ"
                else:
                    perdidas += 1
                    letra = "PERDIÓ"

                # Guardamos la partida apenas termina (si cortás, no se pierden).
                partida = a_pgn(tablero, resultado, motivo, elo, minimate_blancas,
                                nombre_minimate, i + 1)
                print(partida, file=archivo_pgn, end="\n\n")
                archivo_pgn.flush()

                color = "blancas" if minimate_blancas else "negras "
                print(f"[{elo}] partida {i + 1}/{args.partidas} | MiniMate con {color} | "
                      f"{letra} {resultado:7} ({motivo}, {tablero.fullmove_number} jugadas, "
                      f"{segundos:.0f} s) | parcial +{ganadas} ={empatadas} -{perdidas}",
                      flush=True)

            puntos_totales = ganadas + 0.5 * empatadas
            texto_elo, _ = estimar_elo(elo, puntos_totales, args.partidas)
            resumen.append((elo, ganadas, empatadas, perdidas,
                            puntos_totales / args.partidas, texto_elo))
            print()

    # ---- Tabla final ----
    print(f"{'Nivel':>6} {'G':>4} {'E':>4} {'P':>4} {'Puntos':>8} {'Elo MiniMate':>14}")
    print("-" * 44)
    for elo, g, e, p, puntaje, texto_elo in resumen:
        print(f"{elo:>6} {g:>4} {e:>4} {p:>4} {puntaje:>7.0%} {texto_elo:>14}")

    minutos = (time.perf_counter() - inicio_total) / 60
    print(f"\nTiempo total: {minutos:.1f} min. Partidas guardadas en {args.pgn}")
    print("'<' y '>' son cotas: con 0% o 100% la fórmula no da un número exacto.")

    # Aviso: perder todo contra el nivel más bajo que permite Stockfish.
    minimo = min(args.niveles)
    for elo, g, e, p, *_ in resumen:
        if elo == minimo and g == 0 and e == 0 and minimo <= 1320:
            print(f"\nATENCIÓN: MiniMate perdió TODAS las partidas contra {elo}, el mínimo de "
                  "UCI_Elo de Stockfish.\n  Está por debajo de lo que se puede medir así: "
                  "su Elo real es menor que ese número, pero no sabemos cuánto.")


if __name__ == "__main__":
    main()
