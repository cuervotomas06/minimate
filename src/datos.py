# Lectura de partidas a tablas (DataFrames de pandas), para analizar cómo jugás.
#
# Uso típico:
#     from src.datos import cargar_todo
#     partidas, jugadas = cargar_todo()
#     partidas.groupby("color")["resultado"].value_counts()
#
# Dos tablas:
# - partidas: una fila por partida (fecha, color, nivel, resultado, apertura...).
# - jugadas: una fila por jugada (evaluación antes y después, pérdida, fase,
#   piezas colgadas...).
#
# Lee dos "orígenes": las partidas jugadas en la app (origen "minimate") y las
# importadas de Chess.com (origen "chesscom", ver importar_chesscom.py).
# Si hay credenciales de Supabase las lee de la base (src/base_de_datos.py);
# si no, de los archivos datos/partidas.pgn y datos/chesscom.pgn.
#
# Convención para las evaluaciones de las tablas: en centipeones y desde TU
# punto de vista (positivo = bueno para vos), limitadas a +-10 peones como en
# la revisión. Los mates van aparte, en la columna "mate_despues".

import hashlib
import io
import math
import os
from datetime import datetime
from pathlib import Path

import chess
import chess.pgn
import pandas as pd

from src.analisis import (LIMITE_REVISION, PROFUNDIDAD_REVISION, clasificar,
                          jugadas_hasta_mate, perdida_de_la_jugada, valor_posicion)
from src.evaluacion import VALOR_MATE, VALORES
from src import base_de_datos
from src.jugador import clave_del_nombre
from src.motor import es_valor_de_mate

# Archivos locales (cuando no se usa Supabase), en datos/ en la raíz del
# proyecto. Se puede cambiar con la variable de entorno MINIMATE_DATOS (los
# tests la usan para no escribir en la carpeta de verdad).
CARPETA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "datos"
ARCHIVO_PARTIDAS = "partidas.pgn"
ARCHIVO_CHESSCOM = "chesscom.pgn"
ARCHIVO_CACHE = "evaluaciones.parquet"


def carpeta_datos():
    return Path(os.environ.get("MINIMATE_DATOS", CARPETA_POR_DEFECTO))

FASES = ["apertura", "medio juego", "final"]


# ---------------------------------------------------------------------------
# Caché de evaluaciones
# ---------------------------------------------------------------------------
# Evaluar una posición con MiniMate tarda (unos 0,06 s). Una partida tiene ~80
# posiciones, así que mil partidas son más de una hora. Por eso guardamos cada
# evaluación en datos/evaluaciones.parquet: la segunda vez sale al instante.
# La clave es la posición en formato EPD (el FEN sin los contadores de jugadas).

class CacheEvaluaciones:
    def __init__(self, ruta=None):
        self.ruta = Path(ruta) if ruta is not None else carpeta_datos() / ARCHIVO_CACHE
        self.valores = {}
        self.nuevas = 0  # cuántas se agregaron desde la última vez que se guardó
        if self.ruta.exists():
            tabla = pd.read_parquet(self.ruta)
            self.valores = dict(zip(tabla["posicion"], tabla["valor"]))

    def obtener(self, tablero, profundidad=PROFUNDIDAD_REVISION):
        """Evaluación de la posición (desde blancas): de la caché o calculándola."""
        clave = tablero.epd()
        if clave not in self.valores:
            self.valores[clave] = int(valor_posicion(tablero, profundidad))
            self.nuevas += 1
            if self.nuevas >= 200:   # guardamos cada tanto, por si se corta
                self.guardar()
        return self.valores[clave]

    def buscar(self, tablero):
        """Solo mira la caché (sin calcular). None si no está."""
        return self.valores.get(tablero.epd())

    def precargar(self, tableros):
        """Avisa qué posiciones se van a pedir. En el archivo local no hace
        falta (ya está todo en memoria); la de Supabase las pide todas juntas."""

    def guardar(self):
        if self.nuevas == 0 and self.ruta.exists():
            return
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tabla = pd.DataFrame({"posicion": list(self.valores), "valor": list(self.valores.values())})
        tabla.to_parquet(self.ruta, index=False)
        self.nuevas = 0


class CacheVacia(CacheEvaluaciones):
    """Caché que no lee ni guarda nada (calcula si se lo piden). Sirve para
    armar las filas de una partida que ya trae sus [%eval]."""

    def __init__(self):
        self.ruta = None
        self.valores = {}
        self.nuevas = 0

    def guardar(self):
        pass


class CacheSupabase(CacheEvaluaciones):
    """La misma caché, pero en la tabla "evaluaciones" de Supabase."""

    def __init__(self):
        self.ruta = None
        self.valores = {}
        self.pendientes = {}   # calculadas y todavía no subidas

    def precargar(self, tableros):
        faltan = {t.epd() for t in tableros} - set(self.valores)
        if faltan:
            self.valores.update(base_de_datos.leer_evaluaciones(faltan))

    def obtener(self, tablero, profundidad=PROFUNDIDAD_REVISION):
        clave = tablero.epd()
        if clave not in self.valores:
            self.valores[clave] = int(valor_posicion(tablero, profundidad))
            self.pendientes[clave] = self.valores[clave]
            if len(self.pendientes) >= 200:
                self.guardar()
        return self.valores[clave]

    def guardar(self):
        if self.pendientes:
            base_de_datos.guardar_evaluaciones(self.pendientes)
            self.pendientes = {}


# ---------------------------------------------------------------------------
# Aperturas (ECO)
# ---------------------------------------------------------------------------
# Las partidas de Chess.com ya traen el código ECO. Para las de MiniMate usamos
# esta tabla chica con las aperturas más comunes: gana la secuencia más larga
# que coincida con el principio de la partida. Es una aproximación (el ECO
# completo tiene 500 códigos).

APERTURAS = [
    ("e4 e5 Nf3 Nc6 Bb5", "C60", "Ruy López"),
    ("e4 e5 Nf3 Nc6 Bc4 Bc5", "C50", "Giuoco Piano"),
    ("e4 e5 Nf3 Nc6 Bc4 Nf6", "C55", "Dos caballos"),
    ("e4 e5 Nf3 Nc6 Bc4", "C50", "Italiana"),
    ("e4 e5 Nf3 Nc6 d4", "C45", "Escocesa"),
    ("e4 e5 Nf3 Nc6 Nc3", "C46", "Tres caballos"),
    ("e4 e5 Nf3 Nc6", "C44", "Abierta (Nf3 Nc6)"),
    ("e4 e5 Nf3 d6", "C41", "Philidor"),
    ("e4 e5 Nf3 Nf6", "C42", "Petrov"),
    ("e4 e5 Nf3", "C40", "Abierta (Nf3)"),
    ("e4 e5 Nc3", "C25", "Vienesa"),
    ("e4 e5 f4", "C30", "Gambito de rey"),
    ("e4 e5 Bc4", "C23", "Apertura de alfil"),
    ("e4 e5 Qh5", "C20", "Apertura Parham"),
    ("e4 e5", "C20", "Doble peón rey"),
    ("e4 c5", "B20", "Siciliana"),
    ("e4 e6", "C00", "Francesa"),
    ("e4 c6", "B10", "Caro-Kann"),
    ("e4 d5", "B01", "Escandinava"),
    ("e4 d6", "B07", "Pirc"),
    ("e4 Nf6", "B02", "Alekhine"),
    ("e4 g6", "B06", "Moderna"),
    ("e4", "B00", "Peón rey (otras)"),
    ("d4 d5 c4 e6", "D30", "Gambito de dama rehusado"),
    ("d4 d5 c4 dxc4", "D20", "Gambito de dama aceptado"),
    ("d4 d5 c4 c6", "D10", "Eslava"),
    ("d4 d5 c4", "D06", "Gambito de dama"),
    ("d4 d5 Bf4", "D02", "Londres"),
    ("d4 d5", "D00", "Peón dama"),
    ("d4 Nf6 c4 g6", "E60", "India de rey"),
    ("d4 Nf6 c4 e6", "E00", "India de dama / Nimzo"),
    ("d4 Nf6 Bf4", "A46", "Londres"),
    ("d4 Nf6", "A45", "India"),
    ("d4 f5", "A80", "Holandesa"),
    ("d4", "A40", "Peón dama (otras)"),
    ("c4", "A10", "Inglesa"),
    ("Nf3", "A04", "Réti"),
    ("f4", "A02", "Bird"),
    ("b3", "A01", "Larsen"),
    ("g3", "A00", "Benko / irregular"),
]


def clasificar_apertura(jugadas_san):
    """(ECO, nombre) según las primeras jugadas en SAN, o (None, None)."""
    mejor = (None, None)
    largo_mejor = 0
    for secuencia, eco, nombre in APERTURAS:
        pasos = secuencia.split()
        if len(pasos) > largo_mejor and jugadas_san[:len(pasos)] == pasos:
            mejor, largo_mejor = (eco, nombre), len(pasos)
    return mejor


def apertura_de_chesscom(encabezados):
    """Chess.com trae ECO y un link con el nombre: .../openings/Sicilian-Defense-..."""
    eco = encabezados.get("ECO")
    url = encabezados.get("ECOUrl", "")
    nombre = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ") if url else None
    return (eco if eco not in (None, "?", "") else None), (nombre or None)


# ---------------------------------------------------------------------------
# Patrones de principiante
# ---------------------------------------------------------------------------

PIEZAS_GRANDES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def piezas_regaladas(tablero, color):
    """Casillas con piezas de 'color' (sin contar peones ni el rey) que el
    rival, al que le toca mover, puede comer ganando material:
    - sin ninguna defensa, o
    - defendidas, pero atacadas por una pieza de menos valor (el cambio igual
      conviene, por ejemplo un peón que come un caballo)."""
    if tablero.turn == color:
        raise ValueError("Tiene que tocarle mover al rival de 'color'.")
    # Para cada casilla, el valor de la pieza más barata que la puede comer.
    atacante_mas_barato = {}
    for jugada in tablero.legal_moves:
        if tablero.is_capture(jugada) and not tablero.is_en_passant(jugada):
            valor = VALORES[tablero.piece_type_at(jugada.from_square)]
            casilla = jugada.to_square
            atacante_mas_barato[casilla] = min(valor, atacante_mas_barato.get(casilla, math.inf))

    regaladas = []
    for tipo in PIEZAS_GRANDES:
        for casilla in tablero.pieces(tipo, color):
            if casilla not in atacante_mas_barato:
                continue  # nadie la puede comer
            defendida = bool(tablero.attackers(color, casilla))
            if not defendida or atacante_mas_barato[casilla] < VALORES[tipo]:
                regaladas.append(casilla)
    return regaladas


def colgo_pieza(antes, jugada):
    """¿Después de 'jugada' quedó alguna pieza del que movió para regalar?
    No cuenta la pieza que acaba de comer algo de igual o más valor: eso es un
    cambio (por ejemplo Bxc6 dxc6), no un regalo."""
    yo = antes.turn
    capturada = antes.piece_type_at(jugada.to_square)
    if antes.is_en_passant(jugada):
        capturada = chess.PAWN
    movida = antes.piece_type_at(jugada.from_square)
    despues = antes.copy(stack=False)
    despues.push(jugada)
    if despues.is_game_over():
        return False
    regaladas = piezas_regaladas(despues, yo)
    if capturada is not None and VALORES[capturada] >= VALORES[movida] - 50:
        regaladas = [c for c in regaladas if c != jugada.to_square]
    return bool(regaladas)


def dejo_pasar_captura(antes, jugada):
    """¿El rival tenía una pieza para regalar y no la comí?"""
    rival = not antes.turn
    regaladas = piezas_regaladas(antes, rival)
    if not regaladas:
        return False
    return not (antes.is_capture(jugada) and jugada.to_square in regaladas)


def fase_de(tablero, numero):
    """'apertura', 'medio juego' o 'final' según la posición ANTES de la jugada.
    Final: entre los dos bandos quedan 13 peones o menos de piezas (sin contar
    peones ni reyes), por ejemplo dos torres y un alfil. Si no, las primeras
    10 jugadas son la apertura y el resto el medio juego."""
    material = sum(VALORES[tipo] * len(tablero.pieces(tipo, color))
                   for tipo in PIEZAS_GRANDES for color in chess.COLORS)
    if material <= 1300:
        return "final"
    return "apertura" if numero <= 10 else "medio juego"


# ---------------------------------------------------------------------------
# Conversión de valores
# ---------------------------------------------------------------------------

def valor_desde_pgn(puntaje):
    """[%eval] leído por python-chess (PovScore) -> nuestro valor desde blancas."""
    if puntaje is None:
        return None
    blancas = puntaje.white()
    if blancas.is_mate():
        jugadas = blancas.mate()
        medias = max(0, 2 * abs(jugadas) - 1)  # mate en N jugadas ~ 2N-1 medias jugadas
        return (VALOR_MATE - medias) if jugadas > 0 else -(VALOR_MATE - medias)
    return blancas.score()


def para_mi(valor, mi_color):
    """Valor desde blancas -> desde mi punto de vista, limitado a +-10 peones."""
    if valor is None:
        return math.nan
    propio = valor if mi_color == chess.WHITE else -valor
    return float(max(-LIMITE_REVISION, min(LIMITE_REVISION, propio)))


def mate_para_mi(valor, mi_color):
    """Jugadas hasta el mate desde mi punto de vista: +3 = doy mate en 3,
    -2 = me dan mate en 2, 0 = ya es mate. NaN si no hay mate a la vista."""
    if valor is None or not es_valor_de_mate(valor):
        return math.nan
    jugadas = jugadas_hasta_mate(valor)
    gano_yo = (valor > 0) == (mi_color == chess.WHITE)
    return float(jugadas if gano_yo else -jugadas)


def reloj_normalizado(encabezados):
    """Nombre del reloj: 'Reloj' de MiniMate, o TimeControl de Chess.com
    ('180+2' -> '3+2', '600' -> '10+0', '1/86400' -> 'diaria')."""
    if encabezados.get("Reloj"):
        return encabezados["Reloj"]
    control = encabezados.get("TimeControl", "-")
    if control in ("-", "?", ""):
        return "Sin reloj"
    if "/" in control:
        return "diaria"
    partes = control.split("+")
    try:
        inicial = int(partes[0])
        incremento = int(partes[1]) if len(partes) > 1 else 0
    except ValueError:
        return control
    minutos = inicial // 60 if inicial % 60 == 0 else round(inicial / 60, 1)
    return f"{minutos}+{incremento}"


TERMINACIONES_CHESSCOM = [
    ("checkmate", "jaque mate"),
    ("resignation", "abandono"),
    ("abandoned", "abandono"),
    ("insufficient material", "tiempo (sin material para ganar)"),  # "timeout vs insufficient material"
    ("time", "tiempo"),
    ("stalemate", "ahogado"),
    ("repetition", "repetición"),
    ("agreement", "tablas de mutuo acuerdo"),
    ("50 move", "regla de las 50 jugadas"),
]


def terminacion_de(encabezados):
    if encabezados.get("Terminacion"):
        return encabezados["Terminacion"]
    texto = encabezados.get("Termination", "").lower()
    for clave, nombre in TERMINACIONES_CHESSCOM:
        if clave in texto:
            return nombre
    return texto or None


def fecha_de(encabezados):
    fecha = encabezados.get("UTCDate") or encabezados.get("Date", "")
    hora = encabezados.get("Time") or encabezados.get("StartTime") or encabezados.get("UTCTime") or "00:00:00"
    try:
        return pd.Timestamp(datetime.strptime(f"{fecha} {hora}", "%Y.%m.%d %H:%M:%S"))
    except ValueError:
        return pd.NaT


def mi_color_de(encabezados, usuario=None):
    """Con qué color jugué: encabezado MiColor (MiniMate) o comparando mi
    usuario (encabezado MiUsuario o el parámetro) con White/Black."""
    if encabezados.get("MiColor") in ("blancas", "negras"):
        return chess.WHITE if encabezados["MiColor"] == "blancas" else chess.BLACK
    usuario = (usuario or encabezados.get("MiUsuario") or "").lower()
    if usuario and encabezados.get("White", "").lower() == usuario:
        return chess.WHITE
    if usuario and encabezados.get("Black", "").lower() == usuario:
        return chess.BLACK
    return None


# ---------------------------------------------------------------------------
# Clave de cada partida
# ---------------------------------------------------------------------------

def clave_de_juego(juego):
    """Texto que identifica una partida, para no guardarla dos veces.
    Chess.com: su link. MiniMate: un "hash" (resumen corto) de la fecha, los
    jugadores y las jugadas; la misma partida da siempre el mismo hash."""
    link = juego.headers.get("Link")
    if link:
        return link
    partes = [juego.headers.get(nombre, "") for nombre in ("Date", "Time", "White", "Black", "Result")]
    partes += [jugada.uci() for jugada in juego.mainline_moves()]
    return "minimate-" + hashlib.sha1(" ".join(partes).encode("utf-8")).hexdigest()[:20]


def es_del_jugador(encabezados, jugador):
    """¿La partida es de ese jugador? Mira el encabezado "Jugador". Las
    partidas viejas, sin ese encabezado, cuentan como de cualquiera."""
    if jugador is None or not encabezados.get("Jugador"):
        return True
    return clave_del_nombre(encabezados["Jugador"]) == clave_del_nombre(jugador)


# ---------------------------------------------------------------------------
# Leer PGN
# ---------------------------------------------------------------------------

COLUMNAS_PARTIDAS = [
    "partida", "origen", "clave", "fecha", "color", "nivel", "reloj", "resultado", "terminacion",
    "cantidad_jugadas", "eco", "apertura", "jugada_enroque", "menores_desarrolladas",
    "dama_temprana", "mi_elo", "elo_rival", "link",
]
COLUMNAS_JUGADAS = [
    "partida", "origen", "fecha", "indice", "numero", "color", "es_mia", "san", "uci",
    "fen_antes", "reloj_restante", "eval_antes", "eval_despues", "mate_despues",
    "perdida", "clasificacion", "fase", "pieza_colgada", "captura_perdida",
]


def _numero_o_nan(texto):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return math.nan


def leer_pgn(fuente, origen=None, usuario=None, evaluar=False, cache=None, al_avanzar=None,
             jugador=None, con_pgn=False):
    """Lee un PGN y devuelve (partidas, jugadas) como DataFrames.

    fuente: ruta a un archivo .pgn o el texto PGN directamente.
    origen: 'minimate' o 'chesscom' (si no se pasa, sale del encabezado Origen
        o de Site).
    usuario: tu usuario (para saber tu color en partidas de Chess.com).
    evaluar: si es True, las posiciones sin [%eval] se evalúan con MiniMate
        (profundidad 2 con quietud) y quedan en la caché. Si es False solo se
        usa lo que ya esté en la caché (y el resto queda vacío: NaN).
    al_avanzar(hechas, total): para mostrar el progreso al evaluar.
    jugador: si se pasa, solo las partidas de ese jugador (encabezado Jugador).
    con_pgn: si es True, agrega a "partidas" una columna "pgn" con el texto de
        cada partida (para subirla a Supabase).
    """
    if isinstance(fuente, Path) or (isinstance(fuente, str) and "\n" not in fuente
                                    and fuente.lower().endswith(".pgn")):
        texto = Path(fuente).read_text(encoding="utf-8") if Path(fuente).exists() else ""
    else:
        texto = fuente
    cache = cache if cache is not None else CacheEvaluaciones()

    # Primero leemos todas las partidas (para saber el total al evaluar).
    juegos = []
    lector = io.StringIO(texto)
    while (juego := chess.pgn.read_game(lector)) is not None:
        juegos.append(juego)

    filas_partidas, filas_jugadas = [], []
    for numero_partida, juego in enumerate(juegos):
        encabezados = juego.headers
        su_origen = origen or encabezados.get("Origen") or (
            "chesscom" if "chess.com" in encabezados.get("Site", "").lower() else "minimate")
        mi_color = mi_color_de(encabezados, usuario)
        if mi_color is None or juego.errors:
            continue  # no sabemos quién soy, o el PGN está roto: la salteamos
        if not es_del_jugador(encabezados, jugador):
            continue  # es de otro jugador
        identificador = f"{su_origen}-{numero_partida:05d}"
        fecha = fecha_de(encabezados)

        # Recorremos la partida guardando lo de cada posición.
        tablero = juego.board()
        nodos = list(juego.mainline())
        valores = [valor_desde_pgn(juego.eval())]           # posición 0
        valores += [valor_desde_pgn(nodo.eval()) for nodo in nodos]
        tableros = [tablero.copy(stack=False)]
        for nodo in nodos:
            tablero.push(nodo.move)
            tableros.append(tablero.copy(stack=False))
        # Completamos las evaluaciones que falten (de la caché, o calculando).
        cache.precargar([t for k, t in enumerate(tableros) if valores[k] is None])
        for k, posicion in enumerate(tableros):
            if valores[k] is None:
                if posicion.is_game_over():
                    valores[k] = valor_posicion(posicion)  # mate o tablas: no busca
                elif evaluar:
                    valores[k] = cache.obtener(posicion)
                else:
                    valores[k] = cache.buscar(posicion)

        # Datos para la tabla de partidas.
        sans = []
        inicial = tableros[0]
        enroque = math.nan
        menores_movidas = set()
        dama_temprana = False
        for k, nodo in enumerate(nodos):
            antes = tableros[k]
            sans.append(antes.san(nodo.move))
            if antes.turn != mi_color:
                continue
            numero = antes.fullmove_number
            pieza = antes.piece_type_at(nodo.move.from_square)
            if antes.is_castling(nodo.move) and math.isnan(enroque):
                enroque = numero
            if numero <= 10 and pieza in (chess.KNIGHT, chess.BISHOP):
                # Piezas menores que salieron de su casilla inicial.
                if nodo.move.from_square in inicial.pieces(pieza, mi_color):
                    menores_movidas.add(nodo.move.from_square)
            if numero < 5 and pieza == chess.QUEEN:
                dama_temprana = True

        if su_origen == "chesscom":
            eco, apertura = apertura_de_chesscom(encabezados)
        else:
            eco, apertura = clasificar_apertura(sans)

        resultado_pgn = encabezados.get("Result", "*")
        gane = "1-0" if mi_color == chess.WHITE else "0-1"
        if resultado_pgn == gane:
            resultado = "victoria"
        elif resultado_pgn == "1/2-1/2":
            resultado = "tablas"
        elif resultado_pgn in ("1-0", "0-1"):
            resultado = "derrota"
        else:
            resultado = "sin terminar"

        mi_elo = encabezados.get("WhiteElo" if mi_color == chess.WHITE else "BlackElo")
        elo_rival = encabezados.get("BlackElo" if mi_color == chess.WHITE else "WhiteElo")
        filas_partidas.append({
            "partida": identificador,
            "origen": su_origen,
            "clave": clave_de_juego(juego),
            "fecha": fecha,
            "color": "blancas" if mi_color == chess.WHITE else "negras",
            "nivel": encabezados.get("Nivel"),
            "reloj": reloj_normalizado(encabezados),
            "resultado": resultado,
            "terminacion": terminacion_de(encabezados),
            "cantidad_jugadas": math.ceil(len(nodos) / 2),
            "eco": eco,
            "apertura": apertura,
            "jugada_enroque": enroque,
            "menores_desarrolladas": len(menores_movidas),
            "dama_temprana": dama_temprana,
            "mi_elo": _numero_o_nan(mi_elo),
            "elo_rival": _numero_o_nan(elo_rival),
            "link": encabezados.get("Link"),
        })
        if con_pgn:
            filas_partidas[-1]["pgn"] = str(juego)

        # Una fila por jugada.
        for k, nodo in enumerate(nodos):
            antes = tableros[k]
            movio = antes.turn
            es_mia = movio == mi_color
            numero = antes.fullmove_number
            antes_blancas, despues_blancas = valores[k], valores[k + 1]
            if antes_blancas is not None and despues_blancas is not None:
                perdida = float(perdida_de_la_jugada(antes_blancas, despues_blancas, movio))
                clasificacion = clasificar(perdida)
            else:
                perdida, clasificacion = math.nan, None
            filas_jugadas.append({
                "partida": identificador,
                "origen": su_origen,
                "fecha": fecha,
                "indice": k,
                "numero": numero,
                "color": "blancas" if movio == chess.WHITE else "negras",
                "es_mia": es_mia,
                "san": sans[k],
                "uci": nodo.move.uci(),
                "fen_antes": antes.fen(),
                "reloj_restante": nodo.clock() if nodo.clock() is not None else math.nan,
                "eval_antes": para_mi(antes_blancas, mi_color),
                "eval_despues": para_mi(despues_blancas, mi_color),
                "mate_despues": mate_para_mi(despues_blancas, mi_color),
                "perdida": perdida,
                "clasificacion": clasificacion,
                "fase": fase_de(antes, numero),
                # Patrones: solo para tus jugadas (en las del rival quedan vacíos).
                "pieza_colgada": colgo_pieza(antes, nodo.move) if es_mia else None,
                "captura_perdida": dejo_pasar_captura(antes, nodo.move) if es_mia else None,
            })

        if al_avanzar is not None:
            al_avanzar(numero_partida + 1, len(juegos))

    if evaluar:
        cache.guardar()
    columnas = COLUMNAS_PARTIDAS + (["pgn"] if con_pgn else [])
    partidas = pd.DataFrame(filas_partidas, columns=columnas)
    jugadas = pd.DataFrame(filas_jugadas, columns=COLUMNAS_JUGADAS)
    jugadas["fase"] = pd.Categorical(jugadas["fase"], categories=FASES, ordered=True)
    return partidas, jugadas


def tablas_vacias():
    return pd.DataFrame(columns=COLUMNAS_PARTIDAS), pd.DataFrame(columns=COLUMNAS_JUGADAS)


def cargar_todo(carpeta=None, evaluar=False, al_avanzar=None, jugador=None):
    """Lee las dos fuentes (MiniMate y Chess.com) y las junta.
    La columna "origen" dice de dónde viene cada partida.
    jugador: de quién son las partidas (con Supabase es obligatorio).
    Si hay Supabase (y no se pasa una carpeta) lee de la base; si no, de los
    archivos de datos/."""
    if carpeta is None and base_de_datos.hay_supabase():
        return leer_de_supabase(jugador)
    carpeta = Path(carpeta) if carpeta is not None else carpeta_datos()
    cache = CacheEvaluaciones(carpeta / ARCHIVO_CACHE)
    tablas = []
    for archivo, origen in [(ARCHIVO_PARTIDAS, "minimate"), (ARCHIVO_CHESSCOM, "chesscom")]:
        ruta = carpeta / archivo
        if ruta.exists():
            tablas.append(leer_pgn(ruta, origen=origen, evaluar=evaluar, cache=cache,
                                   al_avanzar=al_avanzar, jugador=jugador))
    if not tablas:
        return tablas_vacias()
    partidas = pd.concat([t[0] for t in tablas], ignore_index=True)
    jugadas = pd.concat([t[1] for t in tablas], ignore_index=True)
    jugadas["fase"] = pd.Categorical(jugadas["fase"], categories=FASES, ordered=True)
    return partidas, jugadas


# ---------------------------------------------------------------------------
# Supabase: de filas de la base a DataFrames, y al revés
# ---------------------------------------------------------------------------

# Columnas enteras: en JSON tienen que ir como 10 y no como 10.0 (si no,
# Postgres no las acepta como integer).
ENTERAS = {"cantidad_jugadas", "jugada_enroque", "menores_desarrolladas", "mi_elo",
           "elo_rival", "indice", "numero", "mate_despues"}


def fila_para_base(fila, columnas):
    """Un diccionario listo para mandar en JSON: sin NaN y con enteros de verdad."""
    resultado = {}
    for columna in columnas:
        valor = base_de_datos.limpiar(fila.get(columna))
        if columna in ENTERAS and valor is not None:
            valor = int(valor)
        resultado[columna] = valor
    return resultado


def filas_para_base(partidas, jugadas):
    """[(partida, [jugadas])] de unos DataFrames de leer_pgn(con_pgn=True),
    con las columnas de las tablas de Supabase."""
    columnas_partida = [c for c in COLUMNAS_PARTIDAS if c != "partida"] + ["pgn"]
    columnas_jugada = [c for c in COLUMNAS_JUGADAS if c not in ("partida", "origen", "fecha")]
    resultado = []
    for _, partida in partidas.iterrows():
        suyas = jugadas[jugadas["partida"] == partida["partida"]]
        resultado.append((
            fila_para_base(partida.to_dict(), columnas_partida),
            [fila_para_base(j.to_dict(), columnas_jugada) for _, j in suyas.iterrows()],
        ))
    return resultado


def leer_de_supabase(jugador):
    """(partidas, jugadas) del jugador, leídas de Supabase."""
    if not jugador:
        raise ValueError("Con Supabase hace falta saber de qué jugador leer.")
    from src.jugador import normalizar_nombre
    jugador_id = base_de_datos.id_del_jugador(normalizar_nombre(jugador), clave_del_nombre(jugador))
    filas = base_de_datos.leer_partidas(jugador_id)
    if not filas:
        return tablas_vacias()
    partidas = pd.DataFrame(filas).rename(columns={"id": "partida"})
    # timestamptz llega como texto con zona horaria: lo pasamos a fecha sin zona.
    partidas["fecha"] = pd.to_datetime(partidas["fecha"], utc=True, format="ISO8601").dt.tz_localize(None)
    partidas = partidas.reindex(columns=COLUMNAS_PARTIDAS)
    for columna in ("jugada_enroque", "mi_elo", "elo_rival"):
        partidas[columna] = pd.to_numeric(partidas[columna], errors="coerce").astype(float)

    jugadas = pd.DataFrame(base_de_datos.leer_jugadas(partidas["partida"].tolist()))
    if jugadas.empty:
        jugadas = pd.DataFrame(columns=COLUMNAS_JUGADAS)
    else:
        jugadas = jugadas.rename(columns={"partida_id": "partida"})
        # origen y fecha vienen de la partida (en la base no se repiten).
        jugadas = jugadas.merge(partidas[["partida", "origen", "fecha"]], on="partida", how="left")
        jugadas = jugadas.reindex(columns=COLUMNAS_JUGADAS)
        for columna in ("reloj_restante", "eval_antes", "eval_despues", "mate_despues", "perdida"):
            jugadas[columna] = pd.to_numeric(jugadas[columna], errors="coerce").astype(float)
        jugadas["es_mia"] = jugadas["es_mia"].astype(bool)
    jugadas["fase"] = pd.Categorical(jugadas["fase"], categories=FASES, ordered=True)
    return partidas, jugadas


def fase_de_la_derrota(partidas, jugadas):
    """Para cada partida perdida, la fase de tu peor jugada (la de mayor
    pérdida): una forma simple de ver "dónde se perdió". Devuelve una Serie
    con la cantidad de derrotas por fase."""
    perdidas = partidas.loc[partidas["resultado"] == "derrota", "partida"]
    mias = jugadas[jugadas["es_mia"] & jugadas["partida"].isin(perdidas) & jugadas["perdida"].notna()]
    if mias.empty:
        return pd.Series(0, index=pd.CategoricalIndex(FASES, categories=FASES, ordered=True))
    peores = mias.loc[mias.groupby("partida")["perdida"].idxmax()]
    return peores["fase"].value_counts().reindex(FASES, fill_value=0)

