# La búsqueda "nueva" de MiniMate: piensa durante un TIEMPO (no a una
# profundidad fija) y usa varias técnicas de los motores de verdad.
#
# src/motor.py sigue siendo la búsqueda original (minimax a profundidad fija),
# que se usa para la revisión de partidas y como referencia.
#
# Diferencia de forma: acá usamos "negamax" en vez de minimax. Es lo mismo,
# pero en vez de "blancas maximizan, negras minimizan", cada bando maximiza
# SU puntaje, y el puntaje del rival es el mío con el signo cambiado:
#     valor(posición) = máximo de  -valor(posición después de cada jugada)
# Así hay un solo caso en vez de dos, y las técnicas de abajo son más simples.
# Por dentro, los valores son desde el punto de vista del que mueve; afuera
# (en Resultado) los devolvemos desde blancas, como en el resto de MiniMate.
#
# Técnicas (cada una se puede prender o apagar con Opciones, para medirlas):
# 1. Profundización iterativa: busca a profundidad 1, 2, 3... hasta que se
#    acaba el tiempo, y juega la mejor jugada de la última profundidad
#    COMPLETA. La mejor de cada vuelta se mira primero en la siguiente.
# 2. Tabla de transposiciones: a la misma posición se llega por distintos
#    caminos (e4 Nf6 d4 = d4 Nf6 e4). La guardamos la primera vez y después
#    no la volvemos a analizar.
# 3. Killers e historia: jugadas tranquilas que ya causaron una poda en otra
#    rama (killers) o muchas veces (historia) se miran antes.
# 4. Evaluación avanzada (src/evaluacion_avanzada.py): finales.
# 5. Jugada nula y reducciones tardías (LMR): atajos para mirar menos
#    jugadas que casi seguro son malas.

import time
from dataclasses import dataclass, field, replace

import chess

from src.evaluacion import VALOR_MATE, evaluar
from src.evaluacion_avanzada import evaluar_avanzada
from src.motor import (MARGEN_DELTA, PROFUNDIDAD_MAXIMA_QUIETUD, es_repeticion,
                       ganancia_maxima, jugadas_ruidosas, ordenar_jugadas, puntaje_jugada)

INFINITO = 10 ** 9
LIMITE_MATE = VALOR_MATE - 1000      # más que esto es un mate
PROFUNDIDAD_TOPE = 64

# Tipos de valor guardado en la tabla (por la poda alfa-beta, a veces solo
# sabemos que el valor es "al menos" o "a lo sumo" algo).
EXACTO, AL_MENOS, A_LO_SUMO = 0, 1, 2

CADA_CUANTOS_NODOS = 256   # cada cuántas posiciones miramos el reloj


@dataclass(frozen=True)
class Opciones:
    """Qué técnicas usa la búsqueda (todas prendidas = la versión completa)."""
    iterativa: bool = True        # 1. profundización iterativa
    tabla: bool = True            # 2. tabla de transposiciones
    killers: bool = True          # 3. killers e historia
    evaluacion: str = "avanzada"  # 4. "avanzada" o "clasica" (src/evaluacion.py)
    nula: bool = True             # 5. poda de jugada nula
    lmr: bool = True              # 5. reducciones tardías
    con_quietud: bool = True      # búsqueda de quietud (la de siempre)


# Las versiones que medimos, de a una mejora por vez.
VERSIONES = {
    "v1": Opciones(tabla=False, killers=False, evaluacion="clasica", nula=False, lmr=False),
    "v2": Opciones(killers=False, evaluacion="clasica", nula=False, lmr=False),
    "v3": Opciones(evaluacion="clasica", nula=False, lmr=False),
    "v4": Opciones(nula=False, lmr=False),
    "v5": Opciones(),
}
# Sin nada: se comporta igual que src/motor.py (para los niveles fáciles).
BASICA = Opciones(tabla=False, killers=False, evaluacion="clasica", nula=False, lmr=False)


class TiempoAgotado(Exception):
    """Se usa para cortar la búsqueda de golpe cuando se acaba el tiempo."""


@dataclass
class Resultado:
    jugada: chess.Move | None
    valor: int               # desde blancas; mates como en src/motor.py
    profundidad: int         # última profundidad completa
    nodos: int               # posiciones visitadas
    segundos: float
    variante: list = field(default_factory=list)   # la línea que espera (si hay tabla)

    @property
    def nodos_por_segundo(self):
        return self.nodos / self.segundos if self.segundos > 0 else 0.0


# ---------------------------------------------------------------------------
# Mates en la tabla de transposiciones
# ---------------------------------------------------------------------------
# Un mate vale VALOR_MATE menos la distancia (en medias jugadas) DESDE LA RAÍZ.
# Pero la misma posición puede aparecer a otra distancia de la raíz (en otra
# rama u otra búsqueda): por eso en la tabla lo guardamos como distancia
# desde ESA posición, y al leerlo lo volvemos a pasar a distancia desde la raíz.

def a_la_tabla(valor, ply):
    if valor > LIMITE_MATE:
        return valor + ply
    if valor < -LIMITE_MATE:
        return valor - ply
    return valor


def de_la_tabla(valor, ply):
    if valor > LIMITE_MATE:
        return valor - ply
    if valor < -LIMITE_MATE:
        return valor + ply
    return valor


def valor_de_mate(ply):
    """Valor para el que MUEVE si está en jaque mate, a 'ply' medias jugadas de
    la raíz. Igual que src/motor.py: un mate justo después de la jugada de la
    raíz (ply 1) vale VALOR_MATE."""
    return -(VALOR_MATE - (ply - 1))


def clave_de(board):
    """Identifica la posición (piezas, turno, enroques, al paso).
    Es el equivalente a un hash Zobrist: chess.polyglot.zobrist_hash tarda
    ~28 µs en Python (tanto como evaluar la posición) y esta clave ~1 µs."""
    return hash(board._transposition_key())


# ---------------------------------------------------------------------------
# El buscador
# ---------------------------------------------------------------------------

class Buscador:
    """Guarda lo que aprende entre jugadas (tabla, historia): conviene usar
    uno por partida y llamar a nueva_partida() al empezar otra."""

    def __init__(self, opciones=None, tamano_tabla=50_000):
        self.opciones = opciones or Opciones()
        self.tamano_tabla = tamano_tabla
        self.tabla = {}
        self.historia = {}
        self.killers = []
        self.nodos = 0
        self.limite = None
        self.limite_activo = False

    def nueva_partida(self):
        self.tabla.clear()
        self.historia.clear()

    # --- La búsqueda --------------------------------------------------------

    def buscar(self, board, tiempo=None, profundidad_maxima=None):
        """La mejor jugada en 'tiempo' segundos (o hasta 'profundidad_maxima').
        La profundidad 1 se completa siempre, aunque el tiempo sea muy poco:
        así siempre hay una jugada."""
        board = board.copy()       # no tocamos el tablero de quien llama
        inicio = time.perf_counter()
        self.limite = inicio + tiempo if tiempo is not None else None
        self.nodos = 0
        self.killers = [[None, None] for _ in range(PROFUNDIDAD_TOPE + 1)]
        # La historia de jugadas viejas pesa cada vez menos.
        for clave in self.historia:
            self.historia[clave] //= 2

        legales = list(board.legal_moves)
        if not legales:
            return Resultado(None, evaluar(board), 0, 0, 0.0)
        tope = profundidad_maxima or PROFUNDIDAD_TOPE
        if len(legales) == 1:
            tope = 1                    # no hay nada que pensar
        profundidades = range(1, tope + 1) if self.opciones.iterativa else [tope]

        mejor, valor, completa = legales[0], 0, 0
        jugadas_en_la_raiz = len(board.move_stack)
        for profundidad in profundidades:
            inicio_vuelta = time.perf_counter()
            self.limite_activo = profundidad > 1     # la primera vuelta, siempre entera
            try:
                valor_vuelta, jugada_vuelta = self._raiz(board, profundidad,
                                                         mejor if completa else None)
            except TiempoAgotado:
                # La excepción corta la búsqueda en el medio, sin deshacer las
                # jugadas que había hecho en el tablero: las deshacemos acá.
                while len(board.move_stack) > jugadas_en_la_raiz:
                    board.pop()
                break
            mejor, valor, completa = jugada_vuelta, valor_vuelta, profundidad
            if abs(valor) > LIMITE_MATE:
                break                   # ya encontró un mate: más profundo no mejora
            if self.limite is not None:
                ahora = time.perf_counter()
                # Cada vuelta tarda varias veces la anterior: si no llega, ni empezarla.
                if (ahora - inicio_vuelta) * 3 > self.limite - ahora:
                    break

        segundos = time.perf_counter() - inicio
        valor_blancas = valor if board.turn == chess.WHITE else -valor
        return Resultado(mejor, valor_blancas, completa, self.nodos, segundos,
                         self._variante(board, mejor))

    def _raiz(self, board, profundidad, primera):
        alfa, beta = -INFINITO, INFINITO
        jugadas = self._ordenar(board, list(board.legal_moves), 0, primera)
        mejor_valor, mejor_jugada = -INFINITO, None
        for jugada in jugadas:
            board.push(jugada)
            valor = -self._negamax(board, profundidad - 1, -beta, -alfa, 1, True)
            board.pop()
            if valor > mejor_valor:
                mejor_valor, mejor_jugada = valor, jugada
            alfa = max(alfa, valor)
        self._guardar(board, profundidad, mejor_valor, EXACTO, mejor_jugada, 0)
        return mejor_valor, mejor_jugada

    def _negamax(self, board, profundidad, alfa, beta, ply, nula_permitida):
        self._contar_nodo()
        if es_repeticion(board):
            return 0                    # posición repetida = tablas

        alfa_original = alfa
        jugada_tabla = None
        if self.opciones.tabla:
            entrada = self.tabla.get(clave_de(board))
            if entrada is not None:
                prof_guardada, guardado, tipo, jugada_tabla = entrada
                if prof_guardada >= profundidad:
                    valor = de_la_tabla(guardado, ply)
                    if tipo == EXACTO:
                        return valor
                    if tipo == AL_MENOS and valor >= beta:
                        return valor
                    if tipo == A_LO_SUMO and valor <= alfa:
                        return valor

        legales = list(board.legal_moves)
        if not legales:
            return valor_de_mate(ply) if board.is_check() else 0   # mate o ahogado
        if board.is_insufficient_material():
            return 0
        if profundidad <= 0:
            if self.opciones.con_quietud:
                return self._quietud(board, alfa, beta, ply, 0)
            return self._estatica(board, ply)

        en_jaque = board.is_check()

        # 5a. Jugada nula: "si paso el turno y el rival igual no llega a beta,
        # mi posición es tan buena que no vale la pena mirarla entera".
        # No sirve en jaque (pasar sería ilegal) ni con poco material (en los
        # finales pasar el turno a veces SÍ es lo mejor: zugzwang).
        if (self.opciones.nula and nula_permitida and not en_jaque and profundidad >= 3
                and self._material_sin_peones(board, board.turn) >= 500):
            board.push(chess.Move.null())
            valor = -self._negamax(board, profundidad - 3, -beta, -beta + 1, ply + 1, False)
            board.pop()
            if valor >= beta:
                return beta if valor > LIMITE_MATE else valor

        jugadas = self._ordenar(board, legales, ply, jugada_tabla)
        mejor_valor, mejor_jugada = -INFINITO, None
        for numero, jugada in enumerate(jugadas):
            tranquila = not board.is_capture(jugada) and jugada.promotion is None
            es_killer = jugada in self.killers[min(ply, PROFUNDIDAD_TOPE)]
            board.push(jugada)
            # 5b. Reducciones tardías: las jugadas tranquilas que quedaron al
            # final del orden casi nunca son las mejores. Las miramos con una
            # profundidad menos y "ventana nula" (solo para saber si superan
            # alfa); si sorprenden, las miramos bien.
            if (self.opciones.lmr and numero >= 3 and profundidad >= 3 and tranquila
                    and not en_jaque and not es_killer and not board.is_check()):
                valor = -self._negamax(board, profundidad - 2, -alfa - 1, -alfa, ply + 1, True)
                if valor > alfa:
                    valor = -self._negamax(board, profundidad - 1, -beta, -alfa, ply + 1, True)
            else:
                valor = -self._negamax(board, profundidad - 1, -beta, -alfa, ply + 1, True)
            board.pop()

            if valor > mejor_valor:
                mejor_valor, mejor_jugada = valor, jugada
            if valor > alfa:
                alfa = valor
            if alfa >= beta:
                if tranquila and self.opciones.killers:
                    self._recordar_corte(board, jugada, profundidad, ply)
                break

        if mejor_valor <= alfa_original:
            tipo = A_LO_SUMO
        elif mejor_valor >= beta:
            tipo = AL_MENOS
        else:
            tipo = EXACTO
        self._guardar(board, profundidad, mejor_valor, tipo, mejor_jugada, ply)
        return mejor_valor

    def _quietud(self, board, alfa, beta, ply, extra):
        """Igual que quietud() de src/motor.py, en versión negamax."""
        self._contar_nodo()
        if es_repeticion(board):
            return 0
        if extra >= PROFUNDIDAD_MAXIMA_QUIETUD:
            return self._estatica(board, ply)

        en_jaque = board.is_check()
        if en_jaque:
            jugadas = ordenar_jugadas(board)
            if not jugadas:
                return valor_de_mate(ply)
            mejor = estatica = -INFINITO
        else:
            estatica = self._estatica(board, ply)
            if estatica >= beta:
                return estatica           # "quedarse parado" ya alcanza
            alfa = max(alfa, estatica)
            mejor = estatica
            jugadas = jugadas_ruidosas(board)

        for jugada in jugadas:
            # Poda delta: ni ganando la pieza llegamos a alfa.
            if not en_jaque and estatica + ganancia_maxima(board, jugada) + MARGEN_DELTA <= alfa:
                continue
            board.push(jugada)
            valor = -self._quietud(board, -beta, -alfa, ply + 1, extra + 1)
            board.pop()
            if valor > mejor:
                mejor = valor
            if valor > alfa:
                alfa = valor
            if alfa >= beta:
                break
        return mejor

    # --- Ayudas -------------------------------------------------------------

    def _estatica(self, board, ply):
        """Evaluación sin buscar, desde el punto de vista del que mueve."""
        if self.opciones.evaluacion == "clasica":
            valor = evaluar(board)       # (detecta mate y ahogado, como antes)
            if valor == VALOR_MATE:
                valor -= ply - 1
            elif valor == -VALOR_MATE:
                valor += ply - 1
        else:
            valor = evaluar_avanzada(board)
        return valor if board.turn == chess.WHITE else -valor

    def _contar_nodo(self):
        self.nodos += 1
        if self.limite_activo and self.limite is not None and self.nodos % CADA_CUANTOS_NODOS == 0:
            if time.perf_counter() >= self.limite:
                raise TiempoAgotado

    def _ordenar(self, board, jugadas, ply, primera):
        """Orden de las jugadas: primero la de la tabla (o la mejor de la vuelta
        anterior), después capturas y coronaciones (MVV-LVA), después killers,
        y las tranquilas según la historia."""
        if not self.opciones.killers:
            # Igual que src/motor.py (con la "primera" adelante, si hay).
            jugadas = sorted(jugadas, key=lambda j: puntaje_jugada(board, j), reverse=True)
            if primera in jugadas:
                jugadas.remove(primera)
                jugadas.insert(0, primera)
            return jugadas

        killers = self.killers[min(ply, PROFUNDIDAD_TOPE)]

        def puntaje(jugada):
            if jugada == primera:
                return 10 ** 9
            base = puntaje_jugada(board, jugada)
            if board.is_capture(jugada) or jugada.promotion is not None:
                return 10 ** 7 + base
            if jugada == killers[0]:
                return 10 ** 6 + 1
            if jugada == killers[1]:
                return 10 ** 6
            clave = (board.turn, jugada.from_square, jugada.to_square)
            return min(self.historia.get(clave, 0), 10 ** 5) + base

        return sorted(jugadas, key=puntaje, reverse=True)

    def _recordar_corte(self, board, jugada, profundidad, ply):
        killers = self.killers[min(ply, PROFUNDIDAD_TOPE)]
        if jugada != killers[0]:
            killers[1], killers[0] = killers[0], jugada
        clave = (board.turn, jugada.from_square, jugada.to_square)
        self.historia[clave] = self.historia.get(clave, 0) + profundidad * profundidad

    def _guardar(self, board, profundidad, valor, tipo, jugada, ply):
        if not self.opciones.tabla:
            return
        if len(self.tabla) >= self.tamano_tabla:
            self.tabla.clear()            # forma simple de no pasarnos de memoria
        clave = clave_de(board)
        anterior = self.tabla.get(clave)
        # Preferimos quedarnos con lo que se buscó más profundo.
        if anterior is None or anterior[0] <= profundidad:
            self.tabla[clave] = (profundidad, a_la_tabla(valor, ply), tipo, jugada)

    @staticmethod
    def _material_sin_peones(board, color):
        return sum(len(board.pieces(tipo, color)) * valor
                   for tipo, valor in ((chess.KNIGHT, 320), (chess.BISHOP, 330),
                                       (chess.ROOK, 500), (chess.QUEEN, 900)))

    def _variante(self, board, primera, largo=8):
        """La línea esperada, siguiendo las mejores jugadas de la tabla."""
        if primera is None:
            return []
        linea, copia = [primera], board.copy(stack=False)
        copia.push(primera)
        while self.opciones.tabla and len(linea) < largo:
            entrada = self.tabla.get(clave_de(copia))
            if entrada is None or entrada[3] is None or entrada[3] not in copia.legal_moves:
                break
            linea.append(entrada[3])
            copia.push(entrada[3])
        return linea


def con_opciones(opciones, **cambios):
    """Una copia de las opciones con algunos cambios (por ejemplo, sin quietud)."""
    return replace(opciones, **cambios)
