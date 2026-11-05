# Compara minimax con y sin ordenar jugadas: misma posición, misma profundidad.
# Se corre con: python prueba_velocidad.py

import time
import chess

# Importamos el MÓDULO (no solo la función) para poder leer y reiniciar
# su contador global: motor.posiciones_evaluadas
import src.motor as motor

FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
PROFUNDIDAD = 4


def medir(ordenar):
    """Busca la mejor jugada y devuelve (jugada en SAN, posiciones, segundos)."""
    tablero = chess.Board(FEN)
    motor.posiciones_evaluadas = 0          # reiniciamos el contador
    inicio = time.perf_counter()            # cronómetro de alta precisión
    jugada = motor.mejor_jugada(tablero, PROFUNDIDAD, ordenar=ordenar)
    segundos = time.perf_counter() - inicio
    return tablero.san(jugada), motor.posiciones_evaluadas, segundos


print(f"Posición: {FEN}")
print(f"Profundidad: {PROFUNDIDAD}\n")

# Encabezado de la tabla. Los números tipo :<12 o :>12 son el ancho de
# cada columna (< alinea a la izquierda, > a la derecha).
print(f"{'Modo':<12}{'Jugada':<10}{'Posiciones':>12}{'Segundos':>11}")
print("-" * 45)

resultados = {}
for ordenar in (False, True):
    nombre = "Ordenando" if ordenar else "Sin ordenar"
    jugada, posiciones, segundos = medir(ordenar)
    resultados[ordenar] = (posiciones, segundos)
    print(f"{nombre:<12}{jugada:<10}{posiciones:>12,}{segundos:>11.2f}")

# Cuántas veces menos trabajo hizo con orden.
pos_sin, seg_sin = resultados[False]
pos_con, seg_con = resultados[True]
print(f"\nOrdenando evalúa {pos_sin / pos_con:.1f}x menos posiciones "
      f"y tarda {seg_sin / seg_con:.1f}x menos.")
