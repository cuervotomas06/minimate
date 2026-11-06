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
    """Abre la app en nivel Principiante (para que el bot responda rápido).
    Si se pasa un FEN, arranca desde esa posición."""
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    at.select_slider(key="nivel").set_value("Principiante").run()
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


def mandar_desde_tablero(at, uci, fen=None, id_jugada="id-1", **extra):
    """Simula que el JS mandó una jugada con setComponentValue.
    Usamos _run (interno de AppTest) porque no hay un método público para
    darle valor a un componente propio.
    extra: otros datos que manda el JS (tiempo_usado, tiempo_agotado)."""
    valor = {"uci": uci, "fen": fen or at.session_state.tablero.fen(), "id": id_jugada}
    valor.update(extra)
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


# --- Niveles de dificultad -------------------------------------------------

def test_selector_de_nivel_muestra_los_niveles():
    from src.niveles import NIVEL_POR_DEFECTO, NIVELES
    at = AppTest.from_file(RUTA_APP, default_timeout=60).run()
    selector = at.select_slider(key="nivel")
    assert list(selector.options) == list(NIVELES)
    assert selector.value == NIVEL_POR_DEFECTO
    assert "mira" in at.sidebar.caption[0].value  # descripción del nivel


def test_cambiar_de_nivel_no_reinicia_la_partida():
    at = abrir_app()
    at.text_input(key="texto_jugada").input("e4").run()
    at.select_slider(key="nivel").set_value("Fácil").run()
    assert len(jugadas(at)) == 2


# --- Barra de evaluación ---------------------------------------------------

def test_barra_de_evaluacion():
    at = abrir_app()
    assert argumentos(at)["barra"] == {"texto": "0.0", "porcentaje": 50.0}
    mandar_desde_tablero(at, "e2e4")
    # El bot respondió y guardó su evaluación: la barra la usa.
    assert len(at.session_state.evaluaciones) == 1
    barra = argumentos(at)["barra"]
    assert set(barra) == {"texto", "porcentaje"}


def test_barra_se_puede_ocultar():
    at = abrir_app()
    at.toggle(key="mostrar_barra").set_value(False).run()
    assert argumentos(at)["barra"] is None


def test_barra_muestra_el_mate():
    # Mate del loco ya jugado: la barra marca 0-1 (ganaron negras).
    at = abrir_app()
    tablero = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        tablero.push_san(san)
    at.session_state.tablero = tablero
    at.run()
    assert argumentos(at)["barra"] == {"texto": "0-1", "porcentaje": 0.0}


# --- Reloj -----------------------------------------------------------------

def test_sin_reloj_por_defecto():
    at = abrir_app()
    assert argumentos(at)["reloj"] is None


def test_reloj_descuenta_el_tiempo_y_suma_el_incremento():
    at = abrir_app()
    at.selectbox(key="control").set_value("3+2").run()
    assert argumentos(at)["reloj"] == {"w": 180.0, "b": 180.0, "corre": "w"}
    # Pensé 10 segundos (lo mide el navegador): 180 - 10 + 2 = 172.
    mandar_desde_tablero(at, "e2e4", tiempo_usado=10)
    reloj = argumentos(at)["reloj"]
    assert reloj["w"] == 172.0
    assert 180.0 < reloj["b"] <= 182.0   # el bot pensó un poquito y sumó sus 2 s
    assert reloj["corre"] == "w"         # MiniMate ya jugó: me toca


def test_con_reloj_no_se_puede_deshacer():
    at = abrir_app()
    at.selectbox(key="control").set_value("5+3").run()
    mandar_desde_tablero(at, "e2e4", tiempo_usado=1)
    assert at.button(key="deshacer").disabled


def test_se_me_acaba_el_tiempo():
    at = abrir_app()
    at.selectbox(key="control").set_value("3+2").run()
    mandar_desde_tablero(at, None, id_jugada="t", tiempo_agotado=True)
    assert at.session_state.perdio_por_tiempo == chess.WHITE
    assert "acabó el tiempo" in at.error[0].value
    assert argumentos(at)["reloj"]["corre"] is None   # ya no corre ningún reloj
    assert argumentos(at)["mi_turno"] is False
    # Una jugada que llega tarde no se juega.
    mandar_desde_tablero(at, "e2e4", id_jugada="u", tiempo_usado=1)
    assert jugadas(at) == []


def test_jugada_que_llega_sin_tiempo_pierde():
    at = abrir_app()
    at.selectbox(key="control").set_value("3+2").run()
    mandar_desde_tablero(at, "e2e4", tiempo_usado=200)   # más de los 180 que tenía
    assert at.session_state.perdio_por_tiempo == chess.WHITE
    assert jugadas(at) == []


def test_al_bot_se_le_acaba_el_tiempo():
    at = abrir_app()
    at.selectbox(key="control").set_value("3+2").run()
    at.session_state.tiempos = {chess.WHITE: 100.0, chess.BLACK: 0.0001}
    mandar_desde_tablero(at, "e2e4", tiempo_usado=1)
    assert at.session_state.perdio_por_tiempo == chess.BLACK
    assert "Ganaste" in at.success[0].value


# --- Revisión de partida ---------------------------------------------------

def abrir_revision_del_mate_del_loco():
    at = abrir_app()
    tablero = chess.Board()
    for san in "f3 e5 g4 Qh4#".split():
        tablero.push_san(san)
    at.session_state.tablero = tablero
    at.run()
    at.button(key="revisar").click().run()
    return at


def test_revisar_aparece_solo_al_terminar():
    at = abrir_app()
    assert not [b for b in at.button if b.key == "revisar"]


def test_revision_de_la_partida():
    at = abrir_revision_del_mate_del_loco()
    assert not at.exception
    revision = at.session_state.revision
    assert [a["san"] for a in revision] == ["f3", "g4"]
    assert revision[1]["clasificacion"] == "error grave"
    # Resumen y lista de jugadas.
    assert "Errores graves: **1**" in at.markdown[0].value
    assert "g4??" in at.button(key="rev_2").label
    # Empieza mostrando la posición final, sin poder mover.
    args = argumentos(at)
    assert args["mi_turno"] is False
    assert args["fen"] == at.session_state.tablero.fen()
    assert args["flecha"] is None          # la última jugada fue del bot


def test_navegar_la_revision():
    at = abrir_revision_del_mate_del_loco()
    # Tocar g4 en la lista: el tablero muestra la posición después de g4,
    # con una flecha hacia la mejor jugada.
    at.button(key="rev_2").click().run()
    args = argumentos(at)
    despues_de_g4 = chess.Board()
    for san in "f3 e5 g4".split():
        despues_de_g4.push_san(san)
    assert args["fen"] == despues_de_g4.fen()
    assert args["flecha"] == at.session_state.revision[1]["mejor_uci"]
    assert args["ultima"] == "g2g4"
    # ◀ vuelve una jugada (después de e5: jugada del bot, sin flecha).
    at.button(key="rev_anterior").click().run()
    assert at.session_state.indice_revision == 2
    assert argumentos(at)["flecha"] is None
    # ▶ avanza.
    at.button(key="rev_siguiente").click().run()
    assert at.session_state.indice_revision == 3
    # Nueva partida sale de la revisión.
    at.sidebar.button[0].click().run()
    assert at.session_state.revision is None
    assert argumentos(at)["fen"] == chess.STARTING_FEN
