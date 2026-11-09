# Ayudas para entender la partida: la barra de evaluación y la revisión
# de partida (qué jugadas tuyas fueron imprecisiones o errores).
#
# Todo acá es Python "puro" (sin Streamlit), así se puede testear con pytest.
# Convención de siempre: los valores están en centipeones (100 = un peón)
# y desde el punto de vista de blancas (positivo = mejor para blancas).

import math

import chess

from src.evaluacion import VALOR_MATE
from src.motor import es_valor_de_mate, mejor_jugada, valor_jugada

# ---------------------------------------------------------------------------
# Barra de evaluación
# ---------------------------------------------------------------------------

# A partir de +10 (1000 centipeones) la barra ya se ve casi llena.
LIMITE_BARRA = 1000


def jugadas_hasta_mate(valor):
    """Si el valor es un mate, cuántas jugadas del bando que gana faltan.
    El motor guarda en el valor cuántas medias jugadas faltan: 100000 - valor."""
    medias_jugadas = VALOR_MATE - abs(valor)
    # Dos medias jugadas (una de cada bando) = una jugada del que da mate.
    return math.ceil(medias_jugadas / 2)


def formatear_evaluacion(valor):
    """Texto para la barra: '+1.5', '-0.3', '0.0', 'M3' (mate de blancas en 3),
    '-M2' (mate de negras en 2) o '1-0' / '0-1' si ya es mate."""
    if es_valor_de_mate(valor):
        jugadas = jugadas_hasta_mate(valor)
        if jugadas == 0:
            return "1-0" if valor > 0 else "0-1"
        return f"M{jugadas}" if valor > 0 else f"-M{jugadas}"

    peones = round(valor / 100, 1)
    if peones == 0:
        return "0.0"     # sin signo (y evita que aparezca "-0.0")
    return f"{peones:+.1f}"  # el "+" hace que siempre muestre el signo


def porcentaje_barra(valor):
    """Qué parte de la barra (0 a 100) es blanca.
    50 = igualdad. Usamos tanh para que el cambio sea grande cerca del 0
    (un peón se nota) y casi nada después de +10 (ya está ganado):
      +1 -> 61%   +3 -> 79%   +10 o más -> 94%   mate -> 100%."""
    if es_valor_de_mate(valor):
        return 100.0 if valor > 0 else 0.0
    limitado = max(-LIMITE_BARRA, min(LIMITE_BARRA, valor))
    return 50 + 45 * math.tanh(limitado / 400)


def datos_barra(valor):
    """Lo que necesita el componente JS para dibujar la barra."""
    return {"texto": formatear_evaluacion(valor),
            "porcentaje": round(porcentaje_barra(valor), 1)}


# ---------------------------------------------------------------------------
# Revisión de partida
# ---------------------------------------------------------------------------

# Profundidad del análisis de la revisión (con quietud).
PROFUNDIDAD_REVISION = 2

# Cuántos centipeones empeoró la evaluación por tu jugada (de mayor a menor).
UMBRALES = [
    (300, "error grave"),   # más de 3 peones
    (100, "error"),         # más de 1 peón
    (50, "imprecisión"),    # más de medio peón
]

# Para la comparación limitamos los valores a +-10 peones: pasar de +25 a +12
# no es un error (seguís ganando fácil), pero pasar de mate a +2 sí.
LIMITE_REVISION = 1000

SIMBOLOS = {"error grave": "??", "error": "?", "imprecisión": "?!", None: ""}

# Calidad de cada jugada tuya (como en Chess.com). Usa los mismos umbrales que
# la clasificación de arriba, y agrega dos para las jugadas que estuvieron bien:
# "mejor" (la misma que eligió MiniMate) y "buena" (perdió medio peón o menos).
CALIDADES = ["mejor", "buena", "imprecisión", "error", "error grave"]
SIMBOLOS_CALIDAD = {"mejor": "★", "buena": "✓", "imprecisión": "?!", "error": "?",
                    "error grave": "??"}


def calidad_de(analisis):
    """'mejor', 'buena', 'imprecisión', 'error' o 'error grave'."""
    if analisis["san"] == analisis["mejor_san"]:
        return "mejor"
    return analisis["clasificacion"] or "buena"


def clasificar(perdida):
    """Nombre de la clasificación según cuánto empeoró (en centipeones).
    Devuelve None si la jugada estuvo bien."""
    for umbral, nombre in UMBRALES:
        if perdida > umbral:
            return nombre
    return None


def perdida_de_la_jugada(valor_mejor, valor_mia, color):
    """Cuántos centipeones perdiste por no jugar la mejor (0 o más).
    Ojo con la perspectiva: los valores son desde blancas. Si jugás con
    negras, que el valor BAJE es bueno para vos, así que se da vuelta."""
    mejor = max(-LIMITE_REVISION, min(LIMITE_REVISION, valor_mejor))
    mia = max(-LIMITE_REVISION, min(LIMITE_REVISION, valor_mia))
    if color == chess.WHITE:
        perdida = mejor - mia
    else:
        perdida = mia - mejor
    return max(0, perdida)  # por la poda puede salir un poquito negativo


def analizar_jugada(tablero, jugada, indice=None, profundidad=PROFUNDIDAD_REVISION):
    """Analiza UNA jugada (la de 'tablero.turn') comparándola con la mejor según
    MiniMate (profundidad 2 con quietud). Es lo que hace la revisión con cada
    jugada tuya; la app lo usa también en vivo, después de cada jugada, así
    los dos coinciden. Devuelve el diccionario de revisar_partida."""
    color = tablero.turn
    mejor, valor_mejor = mejor_jugada(tablero, profundidad, con_quietud=True,
                                      devolver_valor=True)
    if jugada == mejor:
        valor_mia = valor_mejor  # jugaste la mejor: no hace falta buscar de nuevo
    else:
        valor_mia = valor_jugada(tablero, jugada, profundidad, con_quietud=True)
    perdida = perdida_de_la_jugada(valor_mejor, valor_mia, color)
    analisis = {
        "indice": indice,
        "numero": tablero.fullmove_number,
        "san": tablero.san(jugada),
        "mejor_san": tablero.san(mejor),
        "mejor_uci": mejor.uci(),
        "valor_antes": alejar_mate(valor_mejor),
        "valor": valor_mia,
        "perdida": perdida,
        "clasificacion": clasificar(perdida),
    }
    analisis["calidad"] = calidad_de(analisis)
    return analisis


def revisar_partida(jugadas, color, inicial=None, profundidad=PROFUNDIDAD_REVISION,
                    al_avanzar=None, previos=None):
    """Analiza cada jugada tuya (color) de la partida.

    jugadas: lista de chess.Move desde la posición inicial.
    inicial: tablero de la posición inicial (si es None, la de siempre).
    al_avanzar(hechas, total): se llama después de cada jugada analizada
    (la app lo usa para la barra de progreso).
    previos: {indice: análisis} ya hechos (por ejemplo, en vivo durante la
    partida). Esos no se vuelven a calcular.

    Devuelve una lista con un diccionario por cada jugada tuya:
      indice        posición de la jugada en la lista (0 = primera de la partida)
      numero        número de jugada, ej: 12
      san           tu jugada, ej: 'Qf3'
      mejor_san     la mejor según MiniMate, ej: 'Bg4'
      mejor_uci     la misma en UCI, para dibujar la flecha
      valor_antes   evaluación de la posición ANTES de tu jugada (con la mejor)
      valor         evaluación después de tu jugada (desde blancas)
      perdida       centipeones que perdiste
      clasificacion 'imprecisión' / 'error' / 'error grave' / None
      calidad       'mejor' / 'buena' / 'imprecisión' / 'error' / 'error grave'
    """
    tablero = chess.Board() if inicial is None else inicial.copy()

    # Cuántas jugadas son tuyas (para la barra de progreso): si al empezar
    # te toca a vos, son las de índice par (0, 2, 4...); si no, las impares.
    empezas_vos = tablero.turn == color
    total = sum(1 for i in range(len(jugadas)) if (i % 2 == 0) == empezas_vos)

    resultado = []
    previos = previos or {}
    for indice, jugada in enumerate(jugadas):
        if tablero.turn == color:
            hecho = previos.get(indice)
            if hecho is not None and hecho["san"] == tablero.san(jugada):
                resultado.append(hecho)          # ya analizada (en vivo)
            else:
                resultado.append(analizar_jugada(tablero, jugada, indice, profundidad))
            if al_avanzar is not None:
                al_avanzar(len(resultado), total)
        tablero.push(jugada)

    return resultado


def alejar_mate(valor):
    """Pasa un valor "después de la mejor jugada" a "antes de jugarla".
    El material es el mismo, pero un mate queda una media jugada más lejos:
    si con la mejor jugada ya es mate (100000), ANTES de jugarla es mate
    en 1 (99999), no "1-0"."""
    if not es_valor_de_mate(valor):
        return valor
    return valor - 1 if valor > 0 else valor + 1


def valor_posicion(tablero, profundidad=PROFUNDIDAD_REVISION):
    """Evaluación de una posición (desde blancas), buscando la mejor jugada
    del que mueve. Si la partida ya terminó: mate o tablas (0)."""
    if tablero.is_checkmate():
        # Ganó el que acaba de mover (el que NO le toca).
        return VALOR_MATE if tablero.turn == chess.BLACK else -VALOR_MATE
    if tablero.is_game_over():
        return 0
    _, valor = mejor_jugada(tablero, profundidad, con_quietud=True, devolver_valor=True)
    return alejar_mate(valor)


def evaluaciones_de_la_revision(revision, jugadas, inicial=None,
                                profundidad=PROFUNDIDAD_REVISION):
    """Evaluación de CADA posición de la partida, para la barra de la revisión:
    {cantidad de jugadas hechas: valor}, de 0 (posición inicial) al final.

    Casi todas salen gratis de la revisión: la posición antes de cada jugada
    tuya (valor_antes) y la de después (valor). Las que faltan (la inicial si
    jugás con negras, la final si la última jugada fue del bot) se calculan acá.
    Así todas salen del mismo análisis y ninguna "toma prestado" el valor de
    otra posición."""
    valores = {}
    for analisis in revision:
        valores[analisis["indice"]] = analisis["valor_antes"]
        valores[analisis["indice"] + 1] = analisis["valor"]

    tablero = chess.Board() if inicial is None else inicial.copy()
    for cantidad in range(len(jugadas) + 1):
        if cantidad not in valores:
            valores[cantidad] = valor_posicion(tablero, profundidad)
        if cantidad < len(jugadas):
            tablero.push(jugadas[cantidad])
    return valores


# ---------------------------------------------------------------------------
# Contador de jugadas de la revisión
# ---------------------------------------------------------------------------
# Las listas de jugadas cuentan "medias jugadas" (una de blancas O una de
# negras), pero en ajedrez una jugada son las dos: 13. e4 e5 es la jugada 13.

def numero_y_color(inicial, indice):
    """Número de jugada de ajedrez y color de la media jugada 'indice'
    (0 = la primera de la partida). Ej: (13, chess.WHITE)."""
    # Si empezaron negras, la media jugada 0 ya es "la segunda mitad".
    corrimiento = 0 if inicial.turn == chess.WHITE else 1
    numero = inicial.fullmove_number + (indice + corrimiento) // 2
    color = chess.WHITE if (indice + corrimiento) % 2 == 0 else chess.BLACK
    return numero, color


def texto_contador(inicial, mostradas, total_medias):
    """Texto para la navegación: '13. blancas · 13 de 15'.
    mostradas: cuántas medias jugadas se ven en el tablero (0 = inicio).
    total_medias: cuántas medias jugadas tiene la partida."""
    if total_medias == 0:
        return "Posición inicial"
    ultima, _ = numero_y_color(inicial, total_medias - 1)  # número de la última jugada
    if mostradas == 0:
        return f"Posición inicial · 0 de {ultima}"
    numero, color = numero_y_color(inicial, mostradas - 1)
    nombre = "blancas" if color == chess.WHITE else "negras"
    return f"{numero}. {nombre} · {numero} de {ultima}"


def resumen(revision):
    """Cuántas jugadas hay de cada tipo: {'imprecisión': 2, 'error': 1, ...}."""
    cuenta = {nombre: 0 for _, nombre in reversed(UMBRALES)}
    for analisis in revision:
        if analisis["clasificacion"] is not None:
            cuenta[analisis["clasificacion"]] += 1
    return cuenta
