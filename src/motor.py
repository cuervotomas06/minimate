import math
import chess
from src.evaluacion import evaluar, VALORES, VALOR_MATE

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


# ---------------------------------------------------------------------------
# Mates: cuántas jugadas faltan
# ---------------------------------------------------------------------------
# evaluar() devuelve +-VALOR_MATE para cualquier mate, esté cerca o lejos.
# Para saber "mate en cuántas" (y para que el bot elija el mate más corto)
# le restamos al puntaje la distancia: cuántas medias jugadas ("plies") hay
# desde la posición donde empezó la búsqueda hasta el mate.
#   mate en esta posición:        100000
#   mate dentro de 3 medias jugadas: 99997

def evaluar_con_distancia(board, distancia):
    """Igual que evaluar, pero un mate más lejano vale un poco menos."""
    valor = evaluar(board)
    if valor == VALOR_MATE:
        return valor - distancia
    if valor == -VALOR_MATE:
        return valor + distancia
    return valor


def es_valor_de_mate(valor):
    """True si el puntaje es un mate (y no una ventaja de material)."""
    return abs(valor) > VALOR_MATE - 1000


# ---------------------------------------------------------------------------
# Repeticiones
# ---------------------------------------------------------------------------
# Si una posición ya apareció antes, el rival puede volver a repetirla y
# terminar en tablas por triple repetición. Por eso, dentro de la búsqueda,
# tratamos cualquier posición repetida como empate (0):
# - si MiniMate va ganando, evita repetir (0 es peor que su ventaja);
# - si va perdiendo, busca repetir (0 es mejor que perder).

def es_repeticion(board):
    """True si la posición actual ya apareció antes en la partida."""
    # Atajo rápido: para repetir hacen falta al menos 4 jugadas seguidas sin
    # capturas ni movimientos de peón (halfmove_clock cuenta justo eso).
    # Después de una captura no puede haber repetición, así que en la
    # búsqueda de quietud casi siempre salimos acá sin hacer nada más.
    if board.halfmove_clock < 4:
        return False
    # is_repetition(2): la posición está por segunda vez (o más).
    # (No usamos can_claim_draw(): mira además todas las jugadas siguientes
    # y es mucho más lento.)
    return board.is_repetition(2)


# ---------------------------------------------------------------------------
# Búsqueda de quietud
# ---------------------------------------------------------------------------
# Problema que resuelve ("efecto horizonte"): minimax corta a profundidad fija
# y evalúa la posición aunque haya capturas pendientes. Si la última jugada
# fue "dama come peón", la evaluación ve un peón de más... y no ve que en la
# jugada siguiente le comen la dama.
#
# Solución: al llegar a profundidad 0, en vez de evaluar enseguida, seguimos
# mirando SOLO capturas (y coronaciones) hasta que la posición esté "quieta".

# Tope de jugadas extra en la quietud (para que nunca tarde demasiado).
PROFUNDIDAD_MAXIMA_QUIETUD = 8

# Poda delta: margen de seguridad (en centipeones) para descartar capturas
# que ni en el mejor caso alcanzan. 200 = dos peones, cubre los bonus de
# posición de las tablas.
MARGEN_DELTA = 200


def ganancia_maxima(board, jugada):
    """Lo máximo que puede sumar una captura/coronación: la pieza comida
    más lo que gana el peón al coronar."""
    ganancia = 0
    if board.is_en_passant(jugada):
        ganancia += VALORES[chess.PAWN]
    elif board.is_capture(jugada):
        ganancia += VALORES[board.piece_at(jugada.to_square).piece_type]
    if jugada.promotion is not None:
        ganancia += VALORES[jugada.promotion] - VALORES[chess.PAWN]
    return ganancia


def valor_captura(board, jugada):
    """Orden para la quietud: MVV-LVA más el valor de la coronación.
    (Es puntaje_jugada sin el jaque: gives_check es lento y acá se llama mucho.)"""
    puntaje = 0
    if board.is_capture(jugada):
        victima = chess.PAWN if board.is_en_passant(jugada) else \
            board.piece_at(jugada.to_square).piece_type
        atacante = board.piece_at(jugada.from_square).piece_type
        puntaje += 10 * VALORES[victima] - VALORES[atacante]
    if jugada.promotion is not None:
        puntaje += VALORES[jugada.promotion]
    return puntaje


def jugadas_ruidosas(board):
    """Las jugadas que "cambian mucho" la evaluación: capturas y coronaciones,
    ordenadas de la más prometedora a la menos."""
    jugadas = [j for j in board.legal_moves
               if board.is_capture(j) or j.promotion is not None]
    jugadas.sort(key=lambda j: valor_captura(board, j), reverse=True)
    return jugadas


def quietud(board, alfa, beta, profundidad_extra=0, distancia=0):
    """Sigue buscando solo capturas hasta llegar a una posición tranquila.

    Idea clave ("quedarse parado", stand pat): el bando que mueve NO está
    obligado a capturar. Así que la evaluación actual es un piso: si ninguna
    captura la mejora, se queda con ese valor.
    Si está en jaque no puede "quedarse parado": hay que mirar todas las
    jugadas para salir del jaque.
    distancia: medias jugadas desde donde empezó la búsqueda (para los mates)."""
    global posiciones_evaluadas
    posiciones_evaluadas += 1

    # Posición repetida: la contamos como empate.
    # (Solo puede pasar al salir de un jaque: las capturas nunca repiten.)
    if es_repeticion(board):
        return 0

    if profundidad_extra >= PROFUNDIDAD_MAXIMA_QUIETUD:
        return evaluar_con_distancia(board, distancia)

    if board.is_check():
        # En jaque: todas las jugadas legales (son pocas), sin "quedarse parado".
        jugadas = ordenar_jugadas(board)
        if not jugadas:
            return evaluar_con_distancia(board, distancia)  # en jaque y sin jugadas: mate
        mejor = -math.inf if board.turn == chess.WHITE else math.inf
    else:
        # evaluar ya detecta el ahogado (devuelve 0).
        estatica = evaluar(board)
        jugadas = jugadas_ruidosas(board)
        mejor = estatica  # "quedarse parado": no capturar también es una opción

        # Si quedarse parado ya alcanza para la poda, ni miramos las capturas.
        if board.turn == chess.WHITE:
            if estatica >= beta:
                return estatica
            alfa = max(alfa, estatica)
        else:
            if estatica <= alfa:
                return estatica
            beta = min(beta, estatica)

    # Igual que minimax: blancas maximizan, negras minimizan.
    for jugada in jugadas:
        # Poda delta (solo fuera de jaque): si aun ganando la pieza capturada
        # no llegamos a lo que ya tenemos asegurado, ni la miramos.
        if not board.is_check():
            optimista = ganancia_maxima(board, jugada) + MARGEN_DELTA
            if board.turn == chess.WHITE and estatica + optimista <= alfa:
                continue
            if board.turn == chess.BLACK and estatica - optimista >= beta:
                continue

        board.push(jugada)
        valor = quietud(board, alfa, beta, profundidad_extra + 1, distancia + 1)
        board.pop()
        if board.turn == chess.WHITE:
            mejor = max(mejor, valor)
            alfa = max(alfa, mejor)
        else:
            mejor = min(mejor, valor)
            beta = min(beta, mejor)
        if alfa >= beta:
            break
    return mejor


# ---------------------------------------------------------------------------
# Minimax
# ---------------------------------------------------------------------------

def minimax(board, profundidad, alfa=-math.inf, beta=math.inf, ordenar=True,
            con_quietud=True, distancia=0):
    """Minimax con poda alfa-beta.
    alfa: lo mejor que blancas ya tienen asegurado.
    beta: lo mejor que negras ya tienen asegurado.
    ordenar: si es True, mira primero las jugadas más prometedoras
    (así la poda corta antes).
    con_quietud: si es True, al llegar a profundidad 0 sigue mirando capturas.
    distancia: medias jugadas desde donde empezó la búsqueda (para los mates)."""
    # "global" hace falta para poder MODIFICAR la variable del módulo
    # desde adentro de la función (leerla no lo necesita).
    global posiciones_evaluadas

    # Posición repetida: la contamos como empate (ver es_repeticion).
    if es_repeticion(board):
        posiciones_evaluadas += 1
        return 0

    if board.is_game_over():
        posiciones_evaluadas += 1
        return evaluar_con_distancia(board, distancia)
    if profundidad == 0:
        if con_quietud:
            return quietud(board, alfa, beta, 0, distancia)
        posiciones_evaluadas += 1
        return evaluar(board)

    # Elegimos en qué orden recorrer las jugadas.
    jugadas = ordenar_jugadas(board) if ordenar else board.legal_moves

    if board.turn == chess.WHITE:
        mejor = -math.inf
        for jugada in jugadas:
            board.push(jugada)
            valor = minimax(board, profundidad - 1, alfa, beta, ordenar, con_quietud,
                            distancia + 1)
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
            valor = minimax(board, profundidad - 1, alfa, beta, ordenar, con_quietud,
                            distancia + 1)
            board.pop()
            mejor = min(mejor, valor)
            beta = min(beta, mejor)
            if alfa >= beta:
                break          # poda: blancas nunca dejarían llegar acá
        return mejor


def valor_jugada(board, jugada, profundidad=3, ordenar=True, con_quietud=True):
    """Cuánto vale hacer "jugada" (mirando "profundidad" jugadas en total,
    contando esta). Puntaje desde el punto de vista de blancas.
    Sirve para la revisión de partidas: comparar tu jugada con la mejor."""
    board.push(jugada)
    valor = minimax(board, profundidad - 1, -math.inf, math.inf, ordenar, con_quietud)
    board.pop()
    return valor


def mejor_jugada(board, profundidad=3, ordenar=True, con_quietud=True,
                 devolver_valor=False):
    """Devuelve la mejor jugada para el bando que mueve.
    ordenar y con_quietud se pueden apagar para comparar.

    devolver_valor: si es True devuelve (jugada, valor) en vez de solo la
    jugada. valor es la evaluación de la posición DESPUÉS de esa jugada
    (desde el punto de vista de blancas, en centipeones), con lo mejor de
    los dos bandos. Sale gratis: es el número que ya calculó la búsqueda.
    Si es un mate, los mates se cuentan desde esa posición (ver
    evaluar_con_distancia)."""
    juegan_blancas = board.turn == chess.WHITE
    mejor_valor = -math.inf if juegan_blancas else math.inf
    elegida = None
    alfa, beta = -math.inf, math.inf

    jugadas = ordenar_jugadas(board) if ordenar else board.legal_moves

    for jugada in jugadas:
        board.push(jugada)
        valor = minimax(board, profundidad - 1, alfa, beta, ordenar, con_quietud)
        board.pop()

        # Ojo: solo el valor de la MEJOR jugada es exacto. Las demás pueden
        # haberse cortado por la poda (su valor es "a lo sumo esto").
        if juegan_blancas and valor > mejor_valor:
            mejor_valor, elegida = valor, jugada
            alfa = max(alfa, valor)
        elif not juegan_blancas and valor < mejor_valor:
            mejor_valor, elegida = valor, jugada
            beta = min(beta, valor)

    if devolver_valor:
        if elegida is None:          # sin jugadas: la partida ya terminó
            mejor_valor = evaluar(board)
        return elegida, mejor_valor
    return elegida
