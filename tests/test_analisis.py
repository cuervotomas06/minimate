# Tests de src/analisis.py: barra de evaluación y revisión de partida.
# Se corren con: pytest

import chess

from src.analisis import (alejar_mate, clasificar, datos_barra,
                          evaluaciones_de_la_revision, formatear_evaluacion,
                          numero_y_color, perdida_de_la_jugada, porcentaje_barra,
                          resumen, revisar_partida, texto_contador, valor_posicion)
from src.evaluacion import VALOR_MATE
from src.motor import mejor_jugada


def tablero_con(jugadas_san):
    tablero = chess.Board()
    for san in jugadas_san.split():
        tablero.push_san(san)
    return tablero


# --- Barra de evaluación ---------------------------------------------------

def test_formato_en_peones():
    assert formatear_evaluacion(150) == "+1.5"
    assert formatear_evaluacion(-30) == "-0.3"
    assert formatear_evaluacion(0) == "0.0"
    assert formatear_evaluacion(-4) == "0.0"   # nada de "-0.0"
    assert formatear_evaluacion(1234) == "+12.3"


def test_formato_de_mate():
    assert formatear_evaluacion(VALOR_MATE - 1) == "M1"      # blancas dan mate en 1
    assert formatear_evaluacion(VALOR_MATE - 2) == "M1"
    assert formatear_evaluacion(VALOR_MATE - 5) == "M3"
    assert formatear_evaluacion(-(VALOR_MATE - 3)) == "-M2"  # negras dan mate en 2
    assert formatear_evaluacion(VALOR_MATE) == "1-0"         # ya es mate
    assert formatear_evaluacion(-VALOR_MATE) == "0-1"


def test_porcentaje_de_la_barra():
    assert porcentaje_barra(0) == 50
    assert 55 < porcentaje_barra(100) < 65                         # un peón se nota
    assert porcentaje_barra(-100) == 100 - porcentaje_barra(100)   # simétrica
    assert 93 < porcentaje_barra(1000) < 96                        # +10: casi llena
    assert porcentaje_barra(5000) == porcentaje_barra(1000)        # más de +10 no cambia
    assert porcentaje_barra(VALOR_MATE - 3) == 100
    assert porcentaje_barra(-(VALOR_MATE - 3)) == 0


def test_datos_barra():
    assert datos_barra(150) == {"texto": "+1.5", "porcentaje": round(porcentaje_barra(150), 1)}


# --- Clasificación de errores ------------------------------------------------

def test_clasificar_por_umbral():
    assert clasificar(0) is None
    assert clasificar(50) is None            # justo 0.5: todavía no
    assert clasificar(51) == "imprecisión"
    assert clasificar(100) == "imprecisión"
    assert clasificar(101) == "error"
    assert clasificar(300) == "error"
    assert clasificar(301) == "error grave"


def test_perdida_segun_el_color():
    # Con blancas: la mejor daba +2, la tuya +0.5 -> perdiste 1.5.
    assert perdida_de_la_jugada(200, 50, chess.WHITE) == 150
    # Con negras los mismos números se leen al revés: +0.5 es MEJOR para
    # negras que +2, así que no perdiste nada.
    assert perdida_de_la_jugada(200, 50, chess.BLACK) == 0
    # Con negras: la mejor daba -2, la tuya -0.5 -> perdiste 1.5.
    assert perdida_de_la_jugada(-200, -50, chess.BLACK) == 150


def test_perdida_limitada_a_10_peones():
    # De +25 a +12 seguís ganando fácil: no es un error.
    assert perdida_de_la_jugada(2500, 1200, chess.WHITE) == 0
    # De mate a +2 sí: perdiste un montón.
    assert perdida_de_la_jugada(VALOR_MATE - 3, 200, chess.WHITE) == 800


# --- Revisión de una partida entera ------------------------------------------

def test_revision_del_mate_del_loco_con_blancas():
    # 1. f3 e5 2. g4?? Qh4#. Revisamos las jugadas de blancas.
    tablero = tablero_con("f3 e5 g4 Qh4#")
    avances = []
    revision = revisar_partida(tablero.move_stack, chess.WHITE,
                               al_avanzar=lambda hechas, total: avances.append((hechas, total)))
    assert [a["san"] for a in revision] == ["f3", "g4"]
    assert [a["indice"] for a in revision] == [0, 2]
    assert revision[1]["clasificacion"] == "error grave"   # g4 permite el mate
    assert revision[1]["mejor_san"] != "g4"
    assert avances == [(1, 2), (2, 2)]                     # para la barra de progreso
    assert resumen(revision)["error grave"] == 1


def test_revision_con_negras():
    # Ahora negras regalan la dama: 1. e4 e5 2. Qh5 Qg5?? 3. Qxg5.
    tablero = tablero_con("e4 e5 Qh5 Qg5 Qxg5")
    revision = revisar_partida(tablero.move_stack, chess.BLACK)
    assert [a["san"] for a in revision] == ["e5", "Qg5"]
    assert revision[1]["clasificacion"] == "error grave"
    assert revision[1]["perdida"] > 300


def test_revision_desde_un_fen():
    # Partida que no empieza en la posición inicial y donde mueven negras primero.
    inicial = chess.Board("4k3/8/8/3q4/8/8/8/3QK3 b - - 0 1")
    tablero = inicial.copy()
    tablero.push_san("Qd2+")   # negras: la dama queda colgada (Kxd2)
    tablero.push_san("Kxd2")
    revision = revisar_partida(tablero.move_stack, chess.BLACK, inicial=inicial)
    assert len(revision) == 1 and revision[0]["san"] == "Qd2+"
    assert revision[0]["clasificacion"] == "error grave"


def test_la_mejor_jugada_no_pierde_nada():
    tablero = chess.Board()
    tablero.push(mejor_jugada(tablero, 2))
    revision = revisar_partida(tablero.move_stack, chess.WHITE)
    assert revision[0]["perdida"] == 0
    assert revision[0]["clasificacion"] is None
    assert revision[0]["san"] == revision[0]["mejor_san"]


# --- Evaluación de cada posición (barra de la revisión) ----------------------

def test_alejar_mate():
    assert alejar_mate(150) == 150                       # material: igual
    assert alejar_mate(VALOR_MATE) == VALOR_MATE - 1     # "1-0" pasa a ser M1
    assert alejar_mate(-(VALOR_MATE - 2)) == -(VALOR_MATE - 3)
    assert formatear_evaluacion(alejar_mate(VALOR_MATE)) == "M1"


def test_valor_posicion():
    assert valor_posicion(tablero_con("f3 e5 g4 Qh4#")) == -VALOR_MATE   # ya es mate
    # Antes de Qh4# negras tienen mate en 1.
    assert formatear_evaluacion(valor_posicion(tablero_con("f3 e5 g4"))) == "-M1"
    # Ahogado: tablas.
    assert valor_posicion(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")) == 0


def test_cada_posicion_tiene_su_evaluacion():
    tablero = tablero_con("f3 e5 g4 Qh4#")
    jugadas = list(tablero.move_stack)
    revision = revisar_partida(jugadas, chess.WHITE)
    valores = evaluaciones_de_la_revision(revision, jugadas)
    assert sorted(valores) == [0, 1, 2, 3, 4]            # todas, de la inicial a la final
    assert formatear_evaluacion(valores[3]) == "-M1"     # después de g4??
    assert formatear_evaluacion(valores[4]) == "0-1"     # mate
    assert valores[3] == revision[1]["valor"]            # sale de la revisión, sin buscar


def test_evaluaciones_jugando_con_negras():
    # Con negras la posición inicial no tiene jugada tuya: se calcula aparte.
    tablero = tablero_con("e4 e5 Qh5 Qg5 Qxg5")
    jugadas = list(tablero.move_stack)
    revision = revisar_partida(jugadas, chess.BLACK)
    valores = evaluaciones_de_la_revision(revision, jugadas)
    assert sorted(valores) == [0, 1, 2, 3, 4, 5]
    assert valores[5] > 500        # después de Qxg5 blancas tienen una dama de más


# --- Contador de jugadas ------------------------------------------------------

def test_contador_en_jugadas_de_ajedrez():
    inicial = chess.Board()
    # 30 medias jugadas = 15 jugadas de ajedrez.
    assert texto_contador(inicial, 25, 30) == "13. blancas · 13 de 15"
    assert texto_contador(inicial, 26, 30) == "13. negras · 13 de 15"
    assert texto_contador(inicial, 1, 30) == "1. blancas · 1 de 15"
    assert texto_contador(inicial, 0, 30) == "Posición inicial · 0 de 15"
    assert texto_contador(inicial, 0, 0) == "Posición inicial"
    # Si la partida termina con una jugada de blancas, esa jugada ya cuenta: 16.
    assert texto_contador(inicial, 31, 31) == "16. blancas · 16 de 16"


def test_contador_desde_un_fen_con_negras():
    # Empieza en la jugada 40 y mueven negras.
    inicial = chess.Board("4k3/8/8/8/8/8/8/4K3 b - - 0 40")
    assert numero_y_color(inicial, 0) == (40, chess.BLACK)
    assert numero_y_color(inicial, 1) == (41, chess.WHITE)
    assert texto_contador(inicial, 2, 3) == "41. blancas · 41 de 41"
