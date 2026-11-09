# Lado Python del tablero interactivo.
#
# declare_component le dice a Streamlit: "hay un componente cuya página
# (index.html + tablero.js) está en esta carpeta". Streamlit la sirve y la
# muestra en un iframe. Lo que le pasamos como argumentos le llega al JS,
# y lo que el JS manda con setComponentValue vuelve acá como valor.

import base64
from pathlib import Path

import chess
import chess.svg
import streamlit.components.v1 as components

CARPETA = Path(__file__).parent

_componente = components.declare_component("tablero_minimate", path=str(CARPETA))


def piezas_svg():
    """Las 12 piezas de python-chess (chess.svg.piece) como data URIs.
    Las claves usan los nombres de chessboard.js: 'wK' = rey blanco, 'bP' = peón negro..."""
    piezas = {}
    for color in chess.COLORS:
        for tipo in chess.PIECE_TYPES:
            pieza = chess.Piece(tipo, color)
            svg = chess.svg.piece(pieza)
            # Un "data URI" mete la imagen entera dentro del texto del enlace,
            # así el navegador no tiene que pedir ningún archivo.
            en_base64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
            nombre = ("w" if color == chess.WHITE else "b") + pieza.symbol().upper()
            piezas[nombre] = "data:image/svg+xml;base64," + en_base64
    return piezas


# Las calculamos una sola vez, al importar el módulo.
PIEZAS = piezas_svg()


def tablero_interactivo(tablero, color_humano, mi_turno, id_respondido, key, on_change=None,
                        barra=None, flecha=None, reloj=None, marca=None):
    """Dibuja el tablero. Cuando el usuario completa una jugada, Streamlit
    guarda en st.session_state[key] un diccionario {uci, fen, id, tiempo_usado}
    y llama a on_change. Si se le acaba el tiempo manda {tiempo_agotado, fen, id}.

    Ayudas opcionales (None = no se muestran):
    - barra: {"texto": "+1.5", "porcentaje": 61.2}  barra de evaluación
    - flecha: "e2e4"  flecha verde (la mejor jugada)
    - marca: {"casilla": "e4", "simbolo": "★", "tipo": "mejor"}  iconito de la
      calidad de tu jugada, arriba de la casilla de destino
    - reloj: {"w": segundos, "b": segundos, "corre": "w" / "b" / None}
    """
    ultima = tablero.peek().uci() if tablero.move_stack else None
    return _componente(
        fen=tablero.fen(),
        color="white" if color_humano == chess.WHITE else "black",
        ultima=ultima,
        mi_turno=mi_turno,
        id_respondido=id_respondido,  # así el JS sabe que ya procesamos su jugada
        piezas=PIEZAS,
        barra=barra,
        flecha=flecha,
        marca=marca,
        reloj=reloj,
        key=key,            # key fija: el iframe no se vuelve a crear en cada rerun
        on_change=on_change,
        default=None,
    )


def procesar_valor(tablero, valor, ultimo_id, color_humano):
    """Interpreta lo que mandó el componente.

    Devuelve (nuevo_ultimo_id, jugada, error):
    - Si el valor no es nuevo (mismo id que el último procesado), no hace nada:
      devuelve (ultimo_id, None, None). Esto evita procesar dos veces la misma jugada.
    - Si es nuevo y válido: (id, jugada, None). La jugada NO se aplica acá.
    - Si es nuevo pero no sirve: (id, None, mensaje de error).
    """
    if not isinstance(valor, dict) or valor.get("id") is None:
        return ultimo_id, None, None
    if valor["id"] == ultimo_id:
        return ultimo_id, None, None  # ya la procesamos en un rerun anterior

    nuevo_id = valor["id"]

    # El FEN que mandó el JS tiene que ser la posición actual. Si no, la
    # jugada se hizo sobre un tablero viejo (por ejemplo, mientras el bot pensaba).
    if valor.get("fen") != tablero.fen():
        return nuevo_id, None, "El tablero estaba desactualizado. Probá de nuevo."
    if tablero.is_game_over() or tablero.turn != color_humano:
        return nuevo_id, None, "Todavía no es tu turno."

    try:
        jugada = chess.Move.from_uci(str(valor.get("uci")))
    except ValueError:
        return nuevo_id, None, "El tablero mandó una jugada que no entiendo."
    if jugada not in tablero.legal_moves:
        return nuevo_id, None, "Esa jugada es ilegal."

    return nuevo_id, jugada, None
