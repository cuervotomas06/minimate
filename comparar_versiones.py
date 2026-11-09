# Enfrenta dos versiones del motor entre sí (por ejemplo v4 contra v5).
#
# Es la forma más sensible de saber si un cambio mejora: las dos versiones
# juegan en la misma compu y al mismo tiempo, así que si la compu se pone más
# lenta, las afecta a las dos por igual.
#
# Cada apertura se juega dos veces, una con cada color, para que ninguna
# versión tenga ventaja por la apertura. Las aperturas son 2 jugadas al azar
# (con semilla fija: siempre las mismas).
#
# Uso:
#   python comparar_versiones.py v4 v5 --aperturas 48 --tiempo 1 --paralelo 8

import argparse
import math
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import chess

from src.busqueda import VERSIONES, Buscador


def aperturas_al_azar(cantidad, semilla=11, medias_jugadas=4):
    """Posiciones de partida variadas: 'medias_jugadas' jugadas legales al azar."""
    azar = random.Random(semilla)
    resultado = []
    while len(resultado) < cantidad:
        tablero = chess.Board()
        for _ in range(medias_jugadas):
            tablero.push(azar.choice(list(tablero.legal_moves)))
        if not tablero.is_game_over() and tablero.fen() not in resultado:
            resultado.append(tablero.fen())
    return resultado


def jugar(fen, version_blancas, version_negras, tiempo, max_jugadas):
    """Una partida. Devuelve el resultado y las posiciones/s de cada versión."""
    tablero = chess.Board(fen)
    buscadores = {chess.WHITE: Buscador(VERSIONES[version_blancas]),
                  chess.BLACK: Buscador(VERSIONES[version_negras])}
    nodos = {chess.WHITE: 0, chess.BLACK: 0}
    segundos = {chess.WHITE: 0.0, chess.BLACK: 0.0}
    while not tablero.is_game_over(claim_draw=True) and tablero.fullmove_number <= max_jugadas:
        r = buscadores[tablero.turn].buscar(tablero, tiempo=tiempo)
        nodos[tablero.turn] += r.nodos
        segundos[tablero.turn] += r.segundos
        tablero.push(r.jugada)
    resultado = tablero.result(claim_draw=True)
    if resultado == "*":
        resultado = "1/2-1/2"         # límite de jugadas: tablas
    return {"blancas": version_blancas, "negras": version_negras, "resultado": resultado,
            "nodos": nodos, "segundos": segundos, "jugadas": tablero.fullmove_number}


def diferencia_elo(puntos):
    """Diferencia de Elo (A menos B) a partir de los puntos de A en cada
    partida (1, 0.5 o 0), y su margen de error con 95% de confianza."""
    n = len(puntos)
    p = sum(puntos) / n
    p_acotado = min(max(p, 0.5 / n), 1 - 0.5 / n)
    diferencia = -400 * math.log10(1 / p_acotado - 1)
    varianza = sum((x - p) ** 2 for x in puntos) / n
    error_p = math.sqrt(varianza / n)
    # Cuánto cambia la diferencia de Elo si el puntaje cambia un poquito.
    pendiente = 400 / (math.log(10) * p_acotado * (1 - p_acotado))
    return diferencia, 1.96 * error_p * pendiente, p


def main():
    parser = argparse.ArgumentParser(description="Enfrenta dos versiones del motor.")
    parser.add_argument("version_a", choices=list(VERSIONES))
    parser.add_argument("version_b", choices=list(VERSIONES))
    parser.add_argument("--aperturas", type=int, default=48)
    parser.add_argument("--tiempo", type=float, default=1.0, help="segundos por jugada")
    parser.add_argument("--paralelo", type=int, default=8)
    parser.add_argument("--max-jugadas", type=int, default=150)
    parser.add_argument("--velocidad-minima", type=float, default=None,
                        help="cortar si las últimas 8 partidas van más lento que esto")
    args = parser.parse_args()

    a, b = args.version_a, args.version_b
    tareas = []
    for fen in aperturas_al_azar(args.aperturas):
        tareas += [(fen, a, b), (fen, b, a)]           # cada apertura, con los dos colores
    print(f"{a} contra {b}: {len(tareas)} partidas, {args.tiempo} s por jugada, "
          f"{args.paralelo} a la vez\n", flush=True)

    puntos_a, velocidades, inicio = [], [], time.perf_counter()
    total = {a: [0, 0.0], b: [0, 0.0]}                  # nodos y segundos de cada versión
    with ProcessPoolExecutor(max_workers=args.paralelo) as pool:
        futuros = [pool.submit(jugar, fen, blancas, negras, args.tiempo, args.max_jugadas)
                   for fen, blancas, negras in tareas]
        for numero, futuro in enumerate(as_completed(futuros), start=1):
            r = futuro.result()
            puntos_blancas = {"1-0": 1.0, "0-1": 0.0}.get(r["resultado"], 0.5)
            puntos_a.append(puntos_blancas if r["blancas"] == a else 1 - puntos_blancas)
            for color, version in ((chess.WHITE, r["blancas"]), (chess.BLACK, r["negras"])):
                total[version][0] += r["nodos"][color]
                total[version][1] += r["segundos"][color]
            nodos = sum(r["nodos"].values())
            segundos = sum(r["segundos"].values())
            velocidades.append((nodos, segundos))
            print(f"[{numero}/{len(tareas)}] {r['blancas']} vs {r['negras']}: {r['resultado']} "
                  f"({r['jugadas']} jugadas, {nodos / segundos:,.0f} pos/s) | "
                  f"{(time.perf_counter() - inicio) / 60:.1f} min", flush=True)
            if args.velocidad_minima and len(velocidades) >= 8:
                n8 = sum(v[0] for v in velocidades[-8:])
                s8 = sum(v[1] for v in velocidades[-8:])
                if n8 / s8 < args.velocidad_minima:
                    print(f"\nVELOCIDAD BAJA: las últimas 8 partidas promediaron {n8 / s8:,.0f} "
                          f"posiciones/s (mínimo {args.velocidad_minima:,.0f}). Corto.", flush=True)
                    pool.shutdown(wait=False, cancel_futures=True)
                    sys.exit(3)

    diferencia, margen, p = diferencia_elo(puntos_a)
    print(f"\n{a} sacó {sum(puntos_a):g} de {len(puntos_a)} ({p:.0%}) contra {b}.")
    print(f"Diferencia de Elo ({a} menos {b}): {diferencia:+.0f} ± {margen:.0f} (95%)")
    for version, (nodos, segundos) in total.items():
        print(f"Posiciones por segundo de {version}: {nodos / segundos:,.0f}")
    print(f"Tiempo total: {(time.perf_counter() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()
