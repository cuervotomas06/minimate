# Interfaz web de MiniMate con Streamlit.
# Se abre con: streamlit run app.py
#
# Cómo funciona Streamlit (importante para entender este archivo):
# cada vez que tocás algo (un botón, un slider, Enter en un cuadro de texto)
# Streamlit vuelve a correr TODO este archivo de arriba a abajo.
# Por eso el tablero se guarda en st.session_state: es un "diccionario"
# que sobrevive entre una corrida y la siguiente.
#
# El tablero es un componente propio hecho en JavaScript
# (src/componente_tablero/). Seleccionar piezas, ver destinos y arrastrar
# pasa todo en el navegador, sin volver a correr este archivo. Recién cuando
# completás una jugada, el componente nos manda su UCI y la procesamos acá.

import chess
import streamlit as st

from src.componente_tablero import procesar_valor, tablero_interactivo
from src.motor import mejor_jugada
from src.niveles import NIVEL_POR_DEFECTO, NIVELES, describir

st.set_page_config(page_title="MiniMate", page_icon="♟")

# Key fija del componente: con la misma key, Streamlit reutiliza el mismo
# iframe en cada rerun en vez de crear uno nuevo (así no parpadea).
KEY_TABLERO = "tablero_js"


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------

def color_humano():
    """Devuelve chess.WHITE o chess.BLACK según lo elegido en la barra lateral."""
    return chess.WHITE if st.session_state.color == "Blancas" else chess.BLACK


def es_mi_turno(tablero):
    return not tablero.is_game_over() and tablero.turn == color_humano()


def nueva_partida():
    """Arranca una partida desde cero."""
    st.session_state.tablero = chess.Board()
    st.session_state.mensaje = ""


def interpretar_jugada(tablero, texto):
    """Convierte el texto del usuario en una jugada.
    Acepta UCI (e2e4, e7e8q) y algebraico (e4, Nf3, O-O).
    Devuelve (jugada, None) si sale bien, o (None, mensaje_de_error)."""
    texto = texto.strip()
    if texto == "":
        return None, "Escribí una jugada."

    # 1) Probamos primero como UCI.
    try:
        jugada = chess.Move.from_uci(texto)
        if jugada in tablero.legal_moves:
            return jugada, None
        return None, f"«{texto}» es ilegal en esta posición."
    except ValueError:
        pass  # no tiene formato UCI: probamos como algebraico

    # 2) Probamos como notación algebraica (SAN).
    #    parse_san ya revisa que la jugada sea legal.
    try:
        return tablero.parse_san(texto), None
    except chess.IllegalMoveError:
        return None, f"«{texto}» es ilegal en esta posición."
    except chess.AmbiguousMoveError:
        return None, (f"«{texto}» es ambigua: hay más de una pieza que puede ir ahí. "
                      "Aclará cuál (por ejemplo Nbd2) o usá UCI.")
    except ValueError:
        return None, (f"No entiendo «{texto}». Usá UCI (e2e4) o algebraico (e4, Nf3). "
                      "Ojo: las piezas van en mayúscula en inglés (N, B, R, Q, K).")


def jugar_humano():
    """Se ejecuta al apretar Enter en el cuadro de texto. Hace la jugada escrita."""
    tablero = st.session_state.tablero
    texto = st.session_state.texto_jugada
    st.session_state.texto_jugada = ""  # vaciamos el cuadro de texto

    if tablero.is_game_over():
        st.session_state.mensaje = "La partida terminó. Empezá una nueva."
        return
    if tablero.turn != color_humano():
        st.session_state.mensaje = "Todavía no es tu turno."
        return

    jugada, error = interpretar_jugada(tablero, texto)
    if error:
        st.session_state.mensaje = error
    else:
        tablero.push(jugada)
        st.session_state.mensaje = ""


def jugada_del_tablero():
    """Se ejecuta cuando el componente manda una jugada (antes de correr el archivo).
    El valor es un diccionario {uci, fen, id}."""
    valor = st.session_state[KEY_TABLERO]
    nuevo_id, jugada, error = procesar_valor(
        st.session_state.tablero, valor, st.session_state.ultimo_id_tablero, color_humano())

    # Guardamos el id aunque la jugada se rechace: así no se procesa dos veces
    # y el componente sabe que ya le contestamos.
    st.session_state.ultimo_id_tablero = nuevo_id
    if jugada is not None:
        st.session_state.tablero.push(jugada)
        st.session_state.mensaje = ""
    elif error:
        st.session_state.mensaje = error


def deshacer():
    """Saca jugadas hasta haber sacado una tuya (y la respuesta del bot si la hubo)."""
    tablero = st.session_state.tablero
    while tablero.move_stack:
        tablero.pop()
        # Después de pop(), le toca mover a quien hizo la jugada que sacamos.
        # Si ese sos vos, ya deshicimos tu jugada: paramos.
        if tablero.turn == color_humano():
            break
    st.session_state.mensaje = ""


def historial_san(tablero):
    """Lista de las jugadas en notación algebraica, ej: ['e4', 'e5', 'Nf3']."""
    # Para escribir cada jugada en SAN hay que conocer la posición de ese momento,
    # así que reproducimos la partida en un tablero nuevo.
    repaso = chess.Board()
    jugadas = []
    for jugada in tablero.move_stack:
        jugadas.append(repaso.san(jugada))
        repaso.push(jugada)
    return jugadas


def texto_estado(tablero):
    """Devuelve (tipo, texto) describiendo cómo está la partida."""
    resultado = tablero.outcome()  # None si la partida sigue
    if resultado is None:
        turno = "Te toca a vos" if tablero.turn == color_humano() else "Le toca a MiniMate"
        if tablero.is_check():
            return "warning", f"¡Jaque! {turno}."
        return "info", f"{turno}."

    if resultado.termination == chess.Termination.CHECKMATE:
        if resultado.winner == color_humano():
            return "success", "¡Jaque mate! Ganaste. 🎉"
        return "error", "Jaque mate. Ganó MiniMate."

    # Todos los demás finales son tablas.
    motivos = {
        chess.Termination.STALEMATE: "ahogado",
        chess.Termination.INSUFFICIENT_MATERIAL: "material insuficiente",
        chess.Termination.SEVENTYFIVE_MOVES: "regla de las 75 jugadas",
        chess.Termination.FIVEFOLD_REPETITION: "quíntuple repetición",
    }
    motivo = motivos.get(resultado.termination, "fin de partida")
    return "info", f"Tablas por {motivo}."


# ---------------------------------------------------------------------------
# Estado inicial (solo la primera vez que se abre la página)
# ---------------------------------------------------------------------------

if "color" not in st.session_state:
    st.session_state.color = "Blancas"
if "tablero" not in st.session_state:
    nueva_partida()
if "ultimo_id_tablero" not in st.session_state:
    st.session_state.ultimo_id_tablero = None  # id de la última jugada del componente

tablero = st.session_state.tablero


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Opciones")
    # Cambiar de color arranca una partida nueva (on_change).
    st.radio("Jugás con", ["Blancas", "Negras"], key="color", on_change=nueva_partida)
    # Dificultad: de menos a más Elo. Se puede cambiar en medio de la partida.
    nombre_nivel = st.select_slider("Dificultad de MiniMate", options=list(NIVELES),
                                    value=NIVEL_POR_DEFECTO, key="nivel")
    st.caption(describir(nombre_nivel))
    nivel = NIVELES[nombre_nivel]
    st.button("Nueva partida", on_click=nueva_partida, width="stretch")


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

st.title("♟ MiniMate")

columna_tablero, columna_panel = st.columns([3, 2])

with columna_tablero:
    tablero_interactivo(
        tablero,
        color_humano=color_humano(),
        mi_turno=es_mi_turno(tablero),
        id_respondido=st.session_state.ultimo_id_tablero,
        key=KEY_TABLERO,
        on_change=jugada_del_tablero,
    )

with columna_panel:
    # Estado de la partida (jaque, mate, tablas...).
    tipo, texto = texto_estado(tablero)
    getattr(st, tipo)(texto)  # llama a st.info / st.warning / st.success / st.error

    # Cuadro para escribir la jugada (alternativa al tablero).
    st.text_input("O escribí tu jugada (e2e4, e4, Nf3...)", key="texto_jugada",
                  on_change=jugar_humano)

    # Mensaje de error de la última jugada, si lo hubo.
    if st.session_state.mensaje:
        st.error(st.session_state.mensaje)

    # Para poder deshacer tiene que existir al menos una jugada tuya.
    # Con negras, la primera jugada siempre es de MiniMate.
    minimo = 1 if color_humano() == chess.WHITE else 2
    st.button("↩ Deshacer mi última jugada", key="deshacer", on_click=deshacer,
              disabled=len(tablero.move_stack) < minimo)

    # Historial: agrupamos de a dos (blancas, negras) por número de jugada.
    st.subheader("Historial")
    jugadas = historial_san(tablero)
    if not jugadas:
        st.caption("Todavía no hay jugadas.")
    else:
        lineas = []
        for i in range(0, len(jugadas), 2):
            numero = i // 2 + 1
            par = " ".join(jugadas[i:i + 2])
            lineas.append(f"{numero}. {par}")
        st.text("\n".join(lineas))


# ---------------------------------------------------------------------------
# Turno de MiniMate
# ---------------------------------------------------------------------------
# Va al final a propósito: así primero se dibuja el tablero con TU jugada
# y recién después el bot piensa. También cubre el caso de jugar con negras:
# al empezar le toca a MiniMate y juega solo. Al volver a correr el archivo
# (st.rerun) el componente recibe el FEN nuevo y anima la jugada del bot.

if not tablero.is_game_over() and tablero.turn != color_humano():
    with st.spinner("MiniMate está pensando..."):
        jugada = mejor_jugada(tablero, nivel["profundidad"], con_quietud=nivel["quietud"])
    tablero.push(jugada)
    st.rerun()
