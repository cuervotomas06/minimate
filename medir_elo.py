# Estima el Elo de MiniMate haciéndolo jugar contra Stockfish con fuerza limitada.
#
# Uso (desde la raíz del proyecto, con el venv activo):
#   python medir_elo.py                              # 10 partidas a 1320, 1500 y 1700
#   python medir_elo.py --partidas 2 --niveles 1320  # prueba rápida
#   python medir_elo.py --profundidad 2 --tiempo 0.05
#   python medir_elo.py --help                       # todas las opciones
#
# Para comparar versiones del motor de forma justa, con TIEMPO fijo por jugada:
#   python medir_elo.py --version v5 --tiempo-minimate 1 --paralelo 8
#   (--version actual = el motor de profundidad fija, eligiendo la profundidad
#    que entra en ese tiempo, como hace la app con el reloj)
#
# Stockfish tiene que estar en la carpeta motores/ (cualquier .exe ahí adentro).
# Las partidas se guardan en un .pgn para revisarlas con cualquier programa de ajedrez.

import argparse
import math
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from src import motor as motor_viejo
from src.busqueda import VERSIONES, Buscador
from src.motor import mejor_jugada
from src.reloj import TIEMPO_ESTIMADO

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
# MiniMate: qué versión juega
# ---------------------------------------------------------------------------

def profundidad_para_tiempo(tiempo, con_quietud=True):
    """La profundidad más grande que entra en 'tiempo' según TIEMPO_ESTIMADO
    (lo mismo que hace la app con el reloj en la versión "actual")."""
    profundidad = 1
    for (prof, quietud), segundos in TIEMPO_ESTIMADO.items():
        if quietud == con_quietud and segundos <= tiempo:
            profundidad = max(profundidad, prof)
    return profundidad


class JugadorMiniMate:
    """Elige las jugadas de MiniMate y cuenta cuántas posiciones miró.
    version: "actual" (src/motor.py, profundidad fija) o v1..v5 (src/busqueda.py).
    tiempo: segundos por jugada (None = profundidad fija, como antes)."""

    def __init__(self, version="actual", tiempo=None, profundidad=3, con_quietud=True):
        self.version, self.tiempo, self.con_quietud = version, tiempo, con_quietud
        self.nodos = 0
        self.segundos = 0.0
        if version == "actual":
            self.profundidad = profundidad if tiempo is None else \
                profundidad_para_tiempo(tiempo, con_quietud)
        else:
            self.buscador = Buscador(VERSIONES[version])

    def jugar(self, tablero):
        inicio = time.perf_counter()
        if self.version == "actual":
            antes = motor_viejo.posiciones_evaluadas
            jugada = mejor_jugada(tablero, self.profundidad, con_quietud=self.con_quietud)
            self.nodos += motor_viejo.posiciones_evaluadas - antes
        else:
            resultado = self.buscador.buscar(tablero, tiempo=self.tiempo)
            jugada = resultado.jugada
            self.nodos += resultado.nodos
        self.segundos += time.perf_counter() - inicio
        return jugada


# ---------------------------------------------------------------------------
# Una partida
# ---------------------------------------------------------------------------

def jugar_partida(motor, elo, minimate_blancas, profundidad, tiempo, max_jugadas,
                  con_quietud=True, jugador=None):
    """Juega una partida completa.
    jugador: un JugadorMiniMate (si no se pasa, profundidad fija como antes).
    Devuelve (puntos de MiniMate: 1, 0.5 o 0, resultado '1-0'/..., motivo, tablero)."""
    jugador = jugador or JugadorMiniMate(profundidad=profundidad, con_quietud=con_quietud)
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
            jugada = jugador.jugar(tablero)
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


def elo_combinado(partidas):
    """Elo que mejor explica TODAS las partidas juntas (contra rivales de
    distinto Elo), y su margen de error con 95% de confianza.

    partidas: lista de (elo del rival, puntos: 1, 0.5 o 0).
    Buscamos el Elo E para el que los puntos esperados (fórmula de Elo:
    1 / (1 + 10^((rival - E) / 400)) por partida) suman lo mismo que los
    puntos que sacó ("máxima verosimilitud"). El margen sale de cuánta
    información dan las partidas: contra rivales parejos, mucha; contra
    rivales que ganan o pierden siempre, poca.
    Devuelve (elo, margen). Si ganó o perdió todo, el elo es una cota y el
    margen es None."""
    def esperado(elo, rival):
        return 1 / (1 + 10 ** ((rival - elo) / 400))

    total = sum(puntos for _, puntos in partidas)
    if total == 0 or total == len(partidas):
        corregido = 0.5 if total == 0 else len(partidas) - 0.5   # media partida de corrección
    else:
        corregido = total
    bajo, alto = -1000.0, 5000.0
    for _ in range(100):                       # búsqueda binaria
        medio = (bajo + alto) / 2
        if sum(esperado(medio, rival) for rival, _ in partidas) < corregido:
            bajo = medio
        else:
            alto = medio
    elo = (bajo + alto) / 2
    if total in (0, len(partidas)):
        return elo, None
    informacion = sum(p * (1 - p) for p in (esperado(elo, rival) for rival, _ in partidas))
    error = 400 / math.log(10) / math.sqrt(informacion)
    return elo, 1.96 * error


# ---------------------------------------------------------------------------
# Varias partidas a la vez (una por núcleo del procesador)
# ---------------------------------------------------------------------------

def _jugar_una(ruta_motor, elo, ronda, minimate_blancas, version, tiempo_mm, profundidad,
               con_quietud, tiempo_sf, max_jugadas, nombre):
    """Una partida en un proceso aparte. Cada partida abre y cierra su propio
    Stockfish ("with"): si el proceso lo dejara abierto, Python no podría
    cerrarlo al final y el programa quedaría colgado."""
    jugador = JugadorMiniMate(version, tiempo_mm, profundidad, con_quietud)
    inicio = time.perf_counter()
    with chess.engine.SimpleEngine.popen_uci(str(ruta_motor)) as stockfish:
        stockfish.configure({"Threads": 1, "Hash": 16})
        configurar_nivel(stockfish, elo)
        puntos, resultado, motivo, tablero = jugar_partida(
            stockfish, elo, minimate_blancas, profundidad, tiempo_sf, max_jugadas,
            con_quietud, jugador)
    pgn = a_pgn(tablero, resultado, motivo, elo, minimate_blancas, nombre, ronda)
    return {"elo": elo, "ronda": ronda, "blancas": minimate_blancas, "puntos": puntos,
            "resultado": resultado, "motivo": motivo, "jugadas": tablero.fullmove_number,
            "segundos": time.perf_counter() - inicio, "pgn": str(pgn),
            "nodos": jugador.nodos, "segundos_minimate": jugador.segundos}


class VelocidadBaja(Exception):
    pass


def vigilar_velocidad(resultados, minima, ultimas=8):
    """Si las últimas partidas jugaron más lento que 'minima' posiciones por
    segundo, lanza VelocidadBaja: con tiempo fijo por jugada, una compu más
    lenta (por ejemplo, a batería o caliente) busca menos y el Elo medido
    sale más bajo. Mejor cortar que medir con datos contaminados."""
    if minima is None or len(resultados) < ultimas:
        return
    recientes = resultados[-ultimas:]
    segundos = sum(r["segundos_minimate"] for r in recientes)
    velocidad = sum(r["nodos"] for r in recientes) / segundos if segundos else 0
    if velocidad < minima:
        raise VelocidadBaja(f"VELOCIDAD BAJA: las últimas {ultimas} partidas promediaron "
                            f"{velocidad:,.0f} posiciones/s (mínimo {minima:,.0f}).")


def medir_en_paralelo(args, ruta_motor, nombre):
    """Juega todas las partidas repartidas en args.paralelo procesos."""
    tareas = [(elo, i + 1, i % 2 == 0) for elo in args.niveles for i in range(args.partidas)]
    resultados = []
    inicio = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.paralelo) as pool, \
            open(args.pgn, "w", encoding="utf-8") as archivo_pgn:
        futuros = [pool.submit(_jugar_una, ruta_motor, elo, ronda, blancas, args.version,
                               args.tiempo_minimate, args.profundidad, not args.sin_quietud,
                               args.tiempo, args.max_jugadas, nombre)
                   for elo, ronda, blancas in tareas]
        for numero, futuro in enumerate(as_completed(futuros), start=1):
            r = futuro.result()
            resultados.append(r)
            print(r["pgn"], file=archivo_pgn, end="\n\n")
            archivo_pgn.flush()
            letra = {1: "GANÓ ", 0.5: "EMPATÓ", 0: "PERDIÓ"}[r["puntos"]]
            color = "blancas" if r["blancas"] else "negras "
            velocidad = r["nodos"] / r["segundos_minimate"] if r["segundos_minimate"] else 0
            print(f"[{numero}/{len(tareas)}] vs {r['elo']} con {color} | {letra} "
                  f"({r['motivo']}, {r['jugadas']} jugadas, {r['segundos']:.0f} s, "
                  f"{velocidad:,.0f} pos/s) | "
                  f"{(time.perf_counter() - inicio) / 60:.1f} min", flush=True)
            try:
                vigilar_velocidad(resultados, args.velocidad_minima)
            except VelocidadBaja as aviso:
                print(f"\n{aviso} Corto la medición.", flush=True)
                for pendiente in futuros:
                    pendiente.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                sys.exit(3)
    return resultados


def imprimir_resumen(resultados, nombre, minutos):
    print(f"\n{nombre}")
    print(f"{'Nivel':>6} {'G':>4} {'E':>4} {'P':>4} {'Puntos':>8}")
    print("-" * 30)
    for elo in sorted({r["elo"] for r in resultados}):
        suyas = [r for r in resultados if r["elo"] == elo]
        g = sum(r["puntos"] == 1 for r in suyas)
        e = sum(r["puntos"] == 0.5 for r in suyas)
        p = sum(r["puntos"] == 0 for r in suyas)
        print(f"{elo:>6} {g:>4} {e:>4} {p:>4} {(g + e / 2) / len(suyas):>7.0%}")
    elo, margen = elo_combinado([(r["elo"], r["puntos"]) for r in resultados])
    nodos = sum(r["nodos"] for r in resultados)
    segundos = sum(r["segundos_minimate"] for r in resultados)
    texto_margen = f"± {margen:.0f}" if margen is not None else "(cota: ganó o perdió todo)"
    print(f"\nElo estimado (todas las partidas juntas): {elo:.0f} {texto_margen} (95%)")
    print(f"Posiciones por segundo de MiniMate: {nodos / segundos:,.0f}" if segundos else "")
    print(f"Partidas: {len(resultados)}  ·  tiempo total: {minutos:.1f} min")


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
    parser.add_argument("--version", default="actual", choices=["actual", *VERSIONES],
                        help="versión del motor: actual (src/motor.py) o v1..v5 (src/busqueda.py)")
    parser.add_argument("--tiempo-minimate", type=float, default=None,
                        help="segundos por jugada para MiniMate (en vez de profundidad fija)")
    parser.add_argument("--paralelo", type=int, default=1,
                        help="cuántas partidas jugar a la vez (por defecto 1)")
    parser.add_argument("--velocidad-minima", type=float, default=None,
                        help="cortar si las últimas 8 partidas de MiniMate van más lento "
                             "que esto (posiciones por segundo)")
    return parser.parse_args()


def main():
    args = leer_argumentos()
    ruta_motor = args.motor or buscar_stockfish()
    con_quietud = not args.sin_quietud
    if args.version != "actual" and args.tiempo_minimate is None:
        sys.exit("Las versiones v1..v5 piensan por tiempo: pasá --tiempo-minimate SEGUNDOS.")
    if args.paralelo > 1 or args.tiempo_minimate is not None:
        if args.version == "actual" and args.tiempo_minimate is not None:
            detalle = f"prof. {profundidad_para_tiempo(args.tiempo_minimate, con_quietud)}"
        else:
            detalle = "profundidad fija" if args.tiempo_minimate is None else "por tiempo"
        nombre = (f"MiniMate {args.version} ({args.tiempo_minimate} s por jugada, {detalle}, "
                  f"{'con' if con_quietud else 'sin'} quietud)")
        print(f"Motor: {ruta_motor}\n{nombre} | {args.partidas} partidas por nivel | "
              f"niveles {args.niveles} | Stockfish {args.tiempo} s | {args.paralelo} a la vez\n")
        inicio = time.perf_counter()
        resultados = medir_en_paralelo(args, ruta_motor, nombre)
        imprimir_resumen(resultados, nombre, (time.perf_counter() - inicio) / 60)
        return
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
