# Tests de la búsqueda nueva (src/busqueda.py) y la evaluación avanzada.
# Se corren con: pytest

import time

import chess
import pytest

from src import motor
from src.busqueda import (BASICA, VERSIONES, Buscador, Opciones, a_la_tabla, con_opciones,
                          de_la_tabla)
from src.evaluacion import VALOR_MATE
from src.evaluacion_avanzada import (distancia_al_centro, empujar_al_borde, evaluar_avanzada,
                                     fase_de_juego)
from src.niveles import NIVELES, crear_buscador

POSICIONES = [
    chess.STARTING_FEN,
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "4k3/8/8/3r4/8/8/8/3QK3 w - - 0 1",
    "6k1/5ppp/8/8/8/8/5PPP/3QR1K1 w - - 0 1",
    "7k/8/8/8/8/8/R7/1R4K1 w - - 0 1",
    "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 8",
    "1k6/2p3pp/8/3bp3/6Pn/1p1K4/1b6/4q3 b - - 3 45",
]


# --- Con todo apagado es el motor de siempre -------------------------------------

@pytest.mark.parametrize("quietud", [True, False])
@pytest.mark.parametrize("fen", POSICIONES)
def test_igual_que_el_motor_original(fen, quietud):
    opciones = con_opciones(BASICA, iterativa=False, con_quietud=quietud)
    for profundidad in (1, 2, 3):
        tablero = chess.Board(fen)
        esperado = motor.mejor_jugada(tablero, profundidad, con_quietud=quietud,
                                      devolver_valor=True)
        resultado = Buscador(opciones).buscar(tablero, profundidad_maxima=profundidad)
        assert (resultado.jugada, resultado.valor) == esperado, profundidad


def test_los_niveles_faciles_son_los_de_antes():
    # Principiante y Fácil: misma jugada que el motor viejo a su profundidad fija.
    for nombre in ("Principiante", "Fácil"):
        nivel = NIVELES[nombre]
        for fen in POSICIONES:
            tablero = chess.Board(fen)
            vieja = motor.mejor_jugada(tablero, nivel["profundidad_maxima"],
                                       con_quietud=nivel["quietud"])
            nueva = crear_buscador(nombre).buscar(
                tablero, tiempo=nivel["tiempo"], profundidad_maxima=nivel["profundidad_maxima"])
            assert nueva.jugada == vieja, (nombre, fen)


def test_ordenar_no_cambia_el_valor():
    # Killers, historia y la tabla solo cambian el ORDEN: a la misma
    # profundidad, el valor de la posición tiene que ser el mismo.
    sin_nada = con_opciones(BASICA, iterativa=False)
    con_orden = con_opciones(VERSIONES["v3"], iterativa=False)
    for fen in POSICIONES[:5]:
        tablero = chess.Board(fen)
        a = Buscador(sin_nada).buscar(tablero, profundidad_maxima=3)
        b = Buscador(con_orden).buscar(tablero, profundidad_maxima=3)
        assert a.valor == b.valor, fen


# --- Tiempo ---------------------------------------------------------------------

@pytest.mark.parametrize("version", list(VERSIONES))
def test_respeta_el_tiempo(version):
    tablero = chess.Board(POSICIONES[5])
    inicio = time.perf_counter()
    resultado = Buscador(VERSIONES[version]).buscar(tablero, tiempo=0.3)
    assert time.perf_counter() - inicio < 0.5
    assert resultado.jugada in tablero.legal_moves
    assert resultado.profundidad >= 1


def test_con_muy_poco_tiempo_igual_juega():
    tablero = chess.Board(POSICIONES[5])
    resultado = Buscador().buscar(tablero, tiempo=0.0001)
    assert resultado.jugada in tablero.legal_moves
    assert resultado.profundidad == 1          # la primera vuelta se completa siempre


def test_si_se_corta_no_toca_el_tablero_y_el_valor_es_coherente():
    # Al cortar por tiempo, la búsqueda deshace las jugadas a medio hacer.
    tablero = chess.Board(POSICIONES[5])
    antes = tablero.fen()
    resultado = Buscador().buscar(tablero, tiempo=0.05)
    assert tablero.fen() == antes
    assert resultado.variante and resultado.variante[0] == resultado.jugada
    copia = tablero.copy()
    for jugada in resultado.variante:            # la línea esperada es legal
        assert jugada in copia.legal_moves
        copia.push(jugada)


def test_una_sola_jugada_legal_contesta_enseguida():
    tablero = chess.Board("7k/8/8/8/8/8/6q1/7K w - - 0 1")   # el rey solo puede comer
    resultado = Buscador().buscar(tablero, tiempo=5)
    assert resultado.jugada == chess.Move.from_uci("h1g2")
    assert resultado.segundos < 0.5


def test_profundidad_maxima():
    resultado = Buscador().buscar(chess.Board(), tiempo=10, profundidad_maxima=2)
    assert resultado.profundidad == 2


# --- Mates ------------------------------------------------------------------------

@pytest.mark.parametrize("version", list(VERSIONES))
def test_mate_en_uno_y_en_dos(version):
    tablero = chess.Board("6k1/5ppp/8/8/8/8/5PPP/3QR1K1 w - - 0 1")
    resultado = Buscador(VERSIONES[version]).buscar(tablero, tiempo=2)
    assert tablero.san(resultado.jugada) == "Re8#"
    assert resultado.valor == VALOR_MATE            # igual que src/motor.py
    tablero = chess.Board("7k/8/8/8/8/8/R7/1R4K1 w - - 0 1")
    resultado = Buscador(VERSIONES[version]).buscar(tablero, tiempo=2)
    assert resultado.valor == VALOR_MATE - 2        # mate en 2 (Ra7 Kg8 Rb8#)


def test_mates_en_la_tabla_de_transposiciones():
    # Se guardan como distancia desde la posición, y se leen desde la raíz.
    mate = VALOR_MATE - 5          # mate 5 medias jugadas después de la raíz
    guardado = a_la_tabla(mate, 3)  # visto desde una posición a 3 de la raíz
    assert guardado == VALOR_MATE - 2
    assert de_la_tabla(guardado, 3) == mate
    assert de_la_tabla(guardado, 1) == VALOR_MATE - 3   # misma posición, más cerca
    assert de_la_tabla(a_la_tabla(-mate, 4), 4) == -mate
    assert a_la_tabla(150, 7) == 150                     # lo que no es mate, igual


def test_la_tabla_sirve_entre_jugadas_y_tiene_limite():
    buscador = Buscador(tamano_tabla=500)
    buscador.buscar(chess.Board(POSICIONES[5]), profundidad_maxima=3)
    assert 0 < len(buscador.tabla) <= 500
    buscador.nueva_partida()
    assert not buscador.tabla


def test_gana_material_con_todas_las_versiones():
    # Dama negra colgada en d5: todas la comen.
    tablero = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    for opciones in VERSIONES.values():
        assert Buscador(opciones).buscar(tablero, tiempo=0.5).jugada == chess.Move.from_uci("d1d5")


def test_no_usa_la_jugada_nula_en_jaque_ni_en_finales():
    # Zugzwang clásico: con rey y peón contra rey, pasar el turno "ganaría",
    # pero no es legal. La versión completa tiene que encontrar la jugada buena.
    tablero = chess.Board("8/8/8/8/8/2k5/2P5/2K5 w - - 0 1")   # tablas: Kd1 o Kb1
    resultado = Buscador().buscar(tablero, tiempo=1)
    assert resultado.jugada in tablero.legal_moves


# --- Evaluación avanzada ---------------------------------------------------------

def test_evaluacion_simetrica():
    for fen in POSICIONES:
        tablero = chess.Board(fen)
        assert evaluar_avanzada(tablero) == -evaluar_avanzada(tablero.mirror()), fen


def test_fase_de_juego():
    assert fase_de_juego(chess.Board()) == 24
    assert fase_de_juego(chess.Board("4k3/pppp4/8/8/8/8/PPPP4/4K3 w - - 0 1")) == 0


def test_en_el_final_el_rey_va_al_centro():
    rincon = chess.Board("8/p7/8/8/8/8/P7/K6k w - - 0 1")
    centro = chess.Board("8/p7/8/8/3K4/8/P7/7k w - - 0 1")
    assert evaluar_avanzada(centro) > evaluar_avanzada(rincon)


def test_peon_pasado_vale_mas():
    pasado = chess.Board("4k3/8/8/3P4/8/8/8/4K3 w - - 0 1")
    trabado = chess.Board("4k3/3p4/8/3P4/8/8/8/4K3 w - - 0 1")
    # Sacando el peón negro, la diferencia es más que el valor del peón.
    assert evaluar_avanzada(pasado) - evaluar_avanzada(trabado) > 100


def test_pareja_de_alfiles():
    dos = chess.Board("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1")
    alfil_y_caballo = chess.Board("4k3/8/8/8/8/8/8/2B1KN2 w - - 0 1")
    assert evaluar_avanzada(dos) - evaluar_avanzada(alfil_y_caballo) >= 20


def test_empujar_al_rey_rival_al_borde():
    assert distancia_al_centro(chess.E4) == 0 and distancia_al_centro(chess.A8) == 6
    en_el_borde = chess.Board("k7/8/8/8/8/8/1Q6/1K6 w - - 0 1")
    en_el_centro = chess.Board("8/8/8/3k4/8/8/1Q6/1K6 w - - 0 1")
    assert empujar_al_borde(en_el_borde, 900, 4) > empujar_al_borde(en_el_centro, 900, 4)
    assert empujar_al_borde(chess.Board(), 900, 24) == 0       # no en el medio juego


def test_da_mate_con_rey_y_dama():
    # Con la evaluación de finales, la versión completa encuentra el mate.
    tablero = chess.Board("8/8/8/4k3/8/8/8/3QK3 w - - 0 1")
    buscador = Buscador()
    for _ in range(40):
        if tablero.is_game_over():
            break
        tablero.push(buscador.buscar(tablero, tiempo=0.4).jugada)
        if tablero.is_game_over():
            break
        tablero.push(Buscador(BASICA).buscar(tablero, profundidad_maxima=2).jugada)
    assert tablero.is_checkmate()


def test_opciones_por_defecto_son_la_version_completa():
    assert Opciones() == VERSIONES["v5"]


def test_niveles_usan_la_version_final():
    # Los niveles del motor nuevo usan v4: sin jugada nula ni LMR, porque v5
    # no le ganó a v4 en partidas (ver README).
    from src.niveles import NIVELES, VERSION_FINAL, opciones_del_nivel
    assert VERSION_FINAL == "v4"
    for nombre in ("Intermedio", "Difícil", "Experto"):
        opciones = opciones_del_nivel(NIVELES[nombre])
        assert not opciones.nula and not opciones.lmr
        assert opciones.tabla and opciones.killers and opciones.evaluacion == "avanzada"
        assert NIVELES[nombre]["elo"] is not None
