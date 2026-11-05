# Tests de la interfaz (app.py) usando AppTest, la herramienta de Streamlit
# que corre la app "sin navegador".
#
# El tablero es un componente en JavaScript: AppTest no ejecuta JS, pero sí
# nos deja ver los datos que Python le manda (sus "argumentos") y simular el
# valor que el JS devolvería cuando el usuario completa una jugada.
# Se corren con: pytest

import json

import chess
from streamlit.testing.v1 import AppTest

# La ruta es relativa a ESTE archivo (tests/), por eso "../app.py".
RUTA_APP = "../app.py"


def abrir_app(fen=None):
    """Abre la app con profundidad 1 (para que el bot responda rápido).
    Si se pasa un FEN, arranca desde esa posición."""
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    at.slider[0].set_value(1).run()
    if fen is not None:
        at.session_state.tablero = chess.Board(fen)
        at.run()
    return at


def componente(at):
    """El elemento del tablero (AppTest lo ve como 'component_instance')."""
    return at.get("component_instance")[0]


def argumentos(at):
    """Lo que Python le pasó al componente JS en la última corrida."""
    return json.loads(componente(at).proto.json_args)


def mandar_desde_tablero(at, uci, fen=None, id_jugada="id-1"):
    """Simula que el JS mandó una jugada con setComponentValue.
    Usamos _run (interno de AppTest) porque no hay un método público para
    darle valor a un componente propio."""
    valor = {"uci": uci, "fen": fen or at.session_state.tablero.fen(), "id": id_jugada}
    estados = at._tree.get_widget_states()        # el estado de los demás widgets
    estado = estados.widgets.add()                # + el valor del tablero
    estado.id = componente(at).proto.id
    estado.json_value = json.dumps(valor)
    at._run(estados)
    return valor


def jugadas(at):
    return at.session_state.tablero.move_stack


# --- Python -> JS ----------------------------------------------------------

def test_abre_y_le_pasa_los_datos_al_tablero():
    at = abrir_app()
    assert not at.exception
    args = argumentos(at)
    assert args["fen"] == chess.STARTING_FEN
    assert args["color"] == "white"
    assert args["mi_turno"] is True
    assert args["ultima"] is None
    assert len(args["piezas"]) == 12
    assert componente(at).proto.id.endswith("tablero_js")  # key fija


def test_jugando_con_negras():
    at = abrir_app()
    at.sidebar.radio[0].set_value("Negras").run()
    args = argumentos(at)
    assert args["color"] == "black"         # el JS da vuelta el tablero
    assert len(jugadas(at)) == 1            # MiniMate abrió
    assert args["ultima"] == jugadas(at)[0].uci()
    assert args["mi_turno"] is True


# --- JS -> Python ----------------------------------------------------------

def test_jugada_del_tablero_y_el_bot_responde():
    at = abrir_app()
    mandar_desde_tablero(at, "e2e4", id_jugada="a")
    assert jugadas(at)[0] == chess.Move.from_uci("e2e4")
    assert len(jugadas(at)) == 2            # MiniMate ya respondió
    args = argumentos(at)
    assert args["fen"] == at.session_state.tablero.fen()
    assert args["ultima"] == jugadas(at)[1].uci()  # el JS anima la jugada del bot
    assert args["id_respondido"] == "a"     # el JS sabe que ya contestamos


def test_la_misma_jugada_no_se_procesa_dos_veces():
    at = abrir_app()
    mandar_desde_tablero(at, "e2e4", id_jugada="a")
    at.run()  # rerun normal: el componente sigue devolviendo el mismo valor
    at.run()
    assert len(jugadas(at)) == 2


def test_deshacer_no_vuelve_a_aplicar_la_jugada_vieja():
    at = abrir_app()
    mandar_desde_tablero(at, "e2e4", id_jugada="a")
    at.button(key="deshacer").click().run()
    # El componente todavía tiene guardado {"uci": "e2e4", "id": "a"},
    # pero como ese id ya se procesó, no se juega de nuevo.
    assert jugadas(at) == []
    assert argumentos(at)["fen"] == chess.STARTING_FEN


def test_jugada_ilegal_del_tablero_muestra_error():
    at = abrir_app()
    mandar_desde_tablero(at, "e2e5", id_jugada="b")
    assert jugadas(at) == []
    assert at.session_state.mensaje == "Esa jugada es ilegal."
    assert argumentos(at)["id_respondido"] == "b"  # el JS vuelve atrás la pieza


def test_promocion_desde_el_tablero():
    at = abrir_app("8/P6k/8/8/8/8/8/4K3 w - - 0 1")
    mandar_desde_tablero(at, "a7a8n")
    assert jugadas(at)[0] == chess.Move.from_uci("a7a8n")


def test_enroque_desde_el_tablero():
    at = abrir_app("r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1")
    mandar_desde_tablero(at, "e1g1")
    assert jugadas(at)[0] == chess.Move.from_uci("e1g1")
    assert at.session_state.tablero.piece_at(chess.F1) == chess.Piece(chess.ROOK, chess.WHITE)


# --- Lo que ya andaba ------------------------------------------------------

def test_texto_y_deshacer_siguen_andando():
    at = abrir_app()
    at.text_input(key="texto_jugada").input("Nf3").run()
    assert len(jugadas(at)) == 2
    assert argumentos(at)["fen"] == at.session_state.tablero.fen()
    at.button(key="deshacer").click().run()
    assert jugadas(at) == []
    assert not at.exception
