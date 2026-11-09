# Guardado de partidas: arma el PGN de una partida jugada en la app y lo guarda.
#
# PGN ("Portable Game Notation") es el formato de texto estándar del ajedrez:
# unos encabezados entre corchetes y después las jugadas. Lichess y Chess.com
# agregan comentarios con el reloj y la evaluación después de cada jugada:
#     1. e4 { [%eval 0.3] [%clk 0:02:58] } e5 { [%eval 0.25] [%clk 0:03:00] }
# Usamos ese mismo formato, así cualquier programa de ajedrez puede leerlo.
#
# El resto de la app solo usa armar_pgn() y guardar_partida(), que decide
# dónde guardar:
# - si hay credenciales de Supabase: en la base (tablas partidas y jugadas);
# - si no: al final de datos/partidas.pgn, como antes.

from datetime import datetime

import chess
import chess.engine
import chess.pgn

from src import base_de_datos
from src.analisis import jugadas_hasta_mate
from src.datos import (ARCHIVO_PARTIDAS, CacheVacia, carpeta_datos, clave_de_juego,
                       filas_para_base, leer_pgn)
from src.evaluacion import VALOR_MATE
from src.jugador import clave_del_nombre, normalizar_nombre
from src.motor import es_valor_de_mate
from src.reloj import CONTROLES


# ---------------------------------------------------------------------------
# Resultado y forma de terminar
# ---------------------------------------------------------------------------

# Cómo terminó, en castellano (para el encabezado "Terminacion").
MOTIVOS = {
    chess.Termination.CHECKMATE: "jaque mate",
    chess.Termination.STALEMATE: "ahogado",
    chess.Termination.INSUFFICIENT_MATERIAL: "material insuficiente",
    chess.Termination.SEVENTYFIVE_MOVES: "regla de las 75 jugadas",
    chess.Termination.FIVEFOLD_REPETITION: "quíntuple repetición",
}


def resultado_y_terminacion(tablero, color_humano, perdio_por_tiempo=None, abandono=False):
    """Devuelve (resultado, termination, terminacion):
    - resultado: '1-0', '0-1' o '1/2-1/2' (como en el PGN).
    - termination: la forma de Lichess ('Normal', 'Time forfeit', 'Abandoned').
    - terminacion: en castellano ('jaque mate', 'tiempo', 'abandono'...).
    Si la partida no terminó devuelve ('*', 'Unterminated', 'sin terminar')."""
    def gana(color):
        return "1-0" if color == chess.WHITE else "0-1"

    if abandono:
        return gana(not color_humano), "Abandoned", "abandono"
    if perdio_por_tiempo is not None:
        ganador = not perdio_por_tiempo
        # Si al que le queda tiempo no le alcanza el material para dar mate: tablas.
        if tablero.has_insufficient_material(ganador):
            return "1/2-1/2", "Time forfeit", "tiempo (sin material para ganar)"
        return gana(ganador), "Time forfeit", "tiempo"

    final = tablero.outcome()
    if final is None:
        return "*", "Unterminated", "sin terminar"
    return final.result(), "Normal", MOTIVOS.get(final.termination, "fin de partida")


# ---------------------------------------------------------------------------
# Armar el PGN
# ---------------------------------------------------------------------------

def puntaje_lichess(valor):
    """Nuestro valor (centipeones desde blancas, mates como 100000 - distancia)
    -> PovScore de python-chess, que se escribe como [%eval 0.35] o [%eval #3]."""
    if es_valor_de_mate(valor):
        jugadas = max(1, jugadas_hasta_mate(valor))
        puntaje = chess.engine.Mate(jugadas if valor > 0 else -jugadas)
    else:
        puntaje = chess.engine.Cp(int(round(valor)))
    return chess.engine.PovScore(puntaje, chess.WHITE)


def time_control(nombre_reloj):
    """'3+2' -> '180+2' (el formato del encabezado TimeControl). Sin reloj: '-'."""
    control = CONTROLES.get(nombre_reloj)
    if control is None:
        return "-"
    inicial, incremento = control
    return f"{inicial}+{incremento}"


def armar_pgn(tablero, color_humano, nivel, reloj, relojes=None, evaluaciones=None,
              perdio_por_tiempo=None, abandono=False, fecha=None, jugador=None,
              clave_jugador=None, calidades=None):
    """Texto PGN de la partida.

    tablero: la partida (con todas sus jugadas).
    nivel: nombre del nivel de MiniMate ('Intermedio', o 'mixto' si cambió).
    reloj: nombre del reloj elegido ('3+2', 'Sin reloj').
    relojes: lista con los segundos que le quedaban al que movió, después de
        cada jugada (None donde no hay dato). Se escribe como [%clk].
    evaluaciones: {cantidad de jugadas: valor} (0 = posición inicial). Se
        escribe como [%eval] después de cada jugada.
    jugador: nombre visible de quien jugó (va en White o Black).
    calidades: {índice de la jugada: "mejor"/"buena"/"imprecisión"/"error"/
        "error grave"} de tus jugadas. Van como comentario [%calidad mejor] y,
        las malas, también con su símbolo estándar (?!, ?, ??) que entiende
        cualquier programa de ajedrez.
    clave_jugador: quién es en MiniMate (encabezado "Jugador"), por ejemplo
        "google:1234...". Si no se pasa, se usa el nombre.
    """
    fecha = fecha or datetime.now()
    relojes = relojes or []
    evaluaciones = evaluaciones or {}
    resultado, termination, terminacion = resultado_y_terminacion(
        tablero, color_humano, perdio_por_tiempo, abandono)

    # from_board copia la partida (y la posición inicial, si no es la de siempre).
    partida = chess.pgn.Game.from_board(tablero)
    yo = normalizar_nombre(jugador) if jugador else "Vos"
    bot = f"MiniMate ({nivel})"
    partida.headers["Event"] = "Partida contra MiniMate"
    partida.headers["Site"] = "MiniMate"
    partida.headers["Date"] = fecha.strftime("%Y.%m.%d")
    partida.headers["Round"] = "-"
    partida.headers["White"] = yo if color_humano == chess.WHITE else bot
    partida.headers["Black"] = bot if color_humano == chess.WHITE else yo
    partida.headers["Result"] = resultado
    partida.headers["Time"] = fecha.strftime("%H:%M:%S")
    partida.headers["TimeControl"] = time_control(reloj)
    partida.headers["Termination"] = termination
    # Encabezados propios (los programas de ajedrez ignoran los que no conocen).
    partida.headers["Origen"] = "minimate"
    partida.headers["MiColor"] = "blancas" if color_humano == chess.WHITE else "negras"
    partida.headers["Nivel"] = nivel
    partida.headers["Reloj"] = reloj
    partida.headers["Terminacion"] = terminacion
    if clave_jugador or jugador:
        partida.headers["Jugador"] = clave_jugador or normalizar_nombre(jugador)

    # La evaluación de la posición inicial va como comentario de la partida.
    if evaluaciones.get(0) is not None:
        partida.set_eval(puntaje_lichess(evaluaciones[0]))

    # Recorremos las jugadas: cada "nodo" es la posición después de una jugada.
    nodo = partida
    cantidad = 0
    while nodo.variations:
        nodo = nodo.variations[0]
        cantidad += 1
        valor = evaluaciones.get(cantidad)
        # En la posición de mate no ponemos [%eval]: el resultado ya lo dice.
        if valor is not None and not nodo.board().is_checkmate():
            nodo.set_eval(puntaje_lichess(valor))
        segundos = relojes[cantidad - 1] if cantidad - 1 < len(relojes) else None
        if segundos is not None:
            nodo.set_clock(max(0.0, float(segundos)))
        calidad = (calidades or {}).get(cantidad - 1)
        if calidad is not None:
            nodo.comment = f"{nodo.comment} [%calidad {CALIDAD_EN_PGN[calidad]}]".strip()
            if calidad in NAG_DE_CALIDAD:
                nodo.nags.add(NAG_DE_CALIDAD[calidad])

    return str(partida)


# Calidad de cada jugada en el PGN: [%calidad ...] (sin tildes ni espacios) y
# los símbolos estándar ("NAG": $6 = ?!, $2 = ?, $4 = ??).
CALIDAD_EN_PGN = {"mejor": "mejor", "buena": "buena", "imprecisión": "imprecision",
                  "error": "error", "error grave": "error_grave"}
NAG_DE_CALIDAD = {"imprecisión": 6, "error": 2, "error grave": 4}


def nombre_de_archivo(fecha=None):
    """Nombre para el botón de descarga, ej: 'minimate_2026-11-06_1530.pgn'."""
    fecha = fecha or datetime.now()
    return fecha.strftime("minimate_%Y-%m-%d_%H%M.pgn")


# ---------------------------------------------------------------------------
# Guardar
# ---------------------------------------------------------------------------

def guardar_partida(pgn, jugador=None):
    """Guarda la partida donde corresponda y devuelve dónde quedó:
    - "Supabase" si hay credenciales de Supabase (a nombre de jugador["id"]);
    - la ruta de datos/partidas.pgn si no.
    jugador: el de la sesión iniciada, {"id", "clave", "nombre"} (ver
        src/cuentas.py). Sin sesión (invitado) no se guarda nada en la base.
    Si Supabase falla (sin internet, error) lanza base_de_datos.ErrorBaseDeDatos:
    la app avisa y ofrece descargar el PGN."""
    if base_de_datos.hay_supabase():
        if not jugador or not jugador.get("id"):
            raise ValueError("Para guardar en la base hace falta un jugador con sesión iniciada.")
        subir_partidas(pgn, jugador_id=jugador["id"])
        return "Supabase"
    return guardar_en_archivo(pgn)


def guardar_en_archivo(pgn):
    """Agrega la partida al final de datos/partidas.pgn y devuelve la ruta."""
    carpeta = carpeta_datos()
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / ARCHIVO_PARTIDAS
    # "a" = append: agrega al final sin borrar lo que ya había.
    # Entre partida y partida va una línea en blanco (así lo pide el formato PGN).
    with open(ruta, "a", encoding="utf-8") as archivo:
        if ruta.stat().st_size > 0:
            archivo.write("\n")
        archivo.write(pgn.strip() + "\n")
    return ruta


def subir_partidas(pgn, jugador=None, origen=None, cache=None, ya_guardadas=None,
                   al_avanzar=None, jugador_si_falta=None, jugador_id=None, evaluar=False):
    """Sube a Supabase todas las partidas de un texto PGN. Devuelve
    (nuevas, repetidas). Las que ya estaban no se duplican.

    jugador_id: id del jugador dueño de TODAS las partidas (lo normal con
        cuentas: el de la sesión iniciada o el dueño de la cuenta vinculada).
    jugador: (para partidas viejas, por nombre) a quién pertenecen. Si es None,
        se usa el encabezado "Jugador" de cada partida, y si no, jugador_si_falta.
    evaluar: si es True, las posiciones sin evaluación se calculan con MiniMate.
    cache: de dónde sacar evaluaciones que falten (por defecto ninguna).
    ya_guardadas: {(jugador, clave de la partida)} ya subidas, para no volver
        a analizarlas (jugador = jugador_id, o la clave del nombre). Si no se
        pasa, la base igual las ignora.
    """
    import io
    cache = cache if cache is not None else CacheVacia()
    ids = {}            # clave del jugador -> id en la base
    ya_guardadas = ya_guardadas if ya_guardadas is not None else set()
    nuevas = repetidas = 0

    juegos = []
    lector = io.StringIO(pgn)
    while (juego := chess.pgn.read_game(lector)) is not None:
        juegos.append(juego)

    for numero, juego in enumerate(juegos, start=1):
        if jugador_id is not None:
            clave_jugador = jugador_id
            ids[clave_jugador] = jugador_id
        else:
            nombre = normalizar_nombre(jugador or juego.headers.get("Jugador") or jugador_si_falta)
            if not nombre:
                raise ValueError("La partida no dice de qué jugador es: pasá jugador_id=...")
            clave_jugador = clave_del_nombre(nombre)
            if clave_jugador not in ids:
                ids[clave_jugador] = base_de_datos.id_del_jugador(nombre, clave_jugador)
        if (clave_jugador, clave_de_juego(juego)) in ya_guardadas:
            repetidas += 1
        else:
            partidas, jugadas = leer_pgn(str(juego), origen=origen, cache=cache, con_pgn=True,
                                         evaluar=evaluar)
            for partida, sus_jugadas in filas_para_base(partidas, jugadas):
                if base_de_datos.guardar_partida(ids[clave_jugador], partida, sus_jugadas):
                    nuevas += 1
                else:
                    repetidas += 1
        if al_avanzar is not None:
            al_avanzar(numero, len(juegos))
    return nuevas, repetidas
