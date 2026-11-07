# Tests de src/datos.py: leer partidas (MiniMate y Chess.com) a DataFrames.
# Se corren con: pytest

import math
from datetime import datetime

import chess
import pytest

import src.datos as datos
from src.analisis import evaluaciones_de_la_revision, revisar_partida
from src.datos import (CacheEvaluaciones, cargar_todo, clasificar_apertura, colgo_pieza,
                       dejo_pasar_captura, fase_de, fase_de_la_derrota, leer_pgn,
                       reloj_normalizado)
from src.guardado import armar_pgn

FECHA = datetime(2026, 11, 6, 15, 30, 0)

# Partida de MiniMate: 1. e4 e5 2. Nf3 Nc6 3. Bc4 Nd4 4. Nxe5 Qg5 5. Nxf7 Qxg2
# 6. Rf1 Qxe4+ 7. Be2 Nf3#  (yo con blancas; caigo en una trampa conocida)
JUGADAS_TRAMPA = "e4 e5 Nf3 Nc6 Bc4 Nd4 Nxe5 Qg5 Nxf7 Qxg2 Rf1 Qxe4+ Be2 Nf3#"

# Partida "de Chess.com" (mismo formato que baja importar_chesscom.py).
PGN_CHESSCOM = """[Origen "chesscom"]
[MiUsuario "yo_mismo"]
[Event "Live Chess"]
[Site "Chess.com"]
[Date "2026.10.01"]
[Round "-"]
[White "Rival123"]
[Black "Yo_Mismo"]
[Result "1-0"]
[ECO "C46"]
[ECOUrl "https://www.chess.com/openings/Three-Knights-Opening"]
[WhiteElo "800"]
[BlackElo "812"]
[TimeControl "600"]
[Termination "Rival123 won by resignation"]
[StartTime "18:00:00"]
[Link "https://www.chess.com/game/live/123456"]

1. e4 {[%clk 0:09:58]} 1... e5 {[%clk 0:09:57]} 2. Nf3 {[%clk 0:09:50]} 2... Qf6 {[%clk 0:09:40]}
3. Nc3 {[%clk 0:09:45]} 3... Bc5 {[%clk 0:09:30]} 4. Bc4 {[%clk 0:09:40]} 4... Nc6 {[%clk 0:09:20]}
5. d3 {[%clk 0:09:30]} 5... Nge7 {[%clk 0:09:10]} 6. O-O {[%clk 0:09:20]} 6... d6 {[%clk 0:09:00]}
7. Bg5 {[%clk 0:09:10]} 7... Qg6 {[%clk 0:08:50]} 8. Nh4 {[%clk 0:09:00]} 8... Qh5 {[%clk 0:08:40]}
9. Bxe7 {[%clk 0:08:50]} 9... Nxe7 {[%clk 0:08:30]} 10. Nf3 {[%clk 0:08:40]} 10... O-O {[%clk 0:08:20]}
11. h3 {[%clk 0:08:30]} 11... Bxh3 {[%clk 0:08:10]} 12. gxh3 {[%clk 0:08:20]} 12... Qxh3 {[%clk 0:08:00]} 1-0
"""


def tablero_con(jugadas_san):
    tablero = chess.Board()
    for san in jugadas_san.split():
        tablero.push_san(san)
    return tablero


def pgn_minimate(jugadas_san=JUGADAS_TRAMPA, color=chess.WHITE, **extra):
    tablero = tablero_con(jugadas_san)
    revision = revisar_partida(tablero.move_stack, color)
    evaluaciones = evaluaciones_de_la_revision(revision, list(tablero.move_stack))
    relojes = [180 - i for i in range(len(tablero.move_stack))]
    return armar_pgn(tablero, color, "Intermedio", "3+2", relojes=relojes,
                     evaluaciones=evaluaciones, fecha=FECHA, **extra)


@pytest.fixture
def cache(tmp_path):
    return CacheEvaluaciones(tmp_path / "evaluaciones.parquet")


# --- Tabla de partidas -----------------------------------------------------------

def test_partida_de_minimate(cache):
    partidas, jugadas = leer_pgn(pgn_minimate(), cache=cache)
    assert len(partidas) == 1 and len(jugadas) == 14
    fila = partidas.iloc[0]
    assert fila["origen"] == "minimate"
    assert fila["fecha"] == datetime(2026, 11, 6, 15, 30)
    assert fila["color"] == "blancas"
    assert fila["nivel"] == "Intermedio"
    assert fila["reloj"] == "3+2"
    assert fila["resultado"] == "derrota"
    assert fila["terminacion"] == "jaque mate"
    assert fila["cantidad_jugadas"] == 7
    assert (fila["eco"], fila["apertura"]) == ("C50", "Italiana")


def test_partida_de_chesscom(cache):
    partidas, jugadas = leer_pgn(PGN_CHESSCOM, cache=cache)
    fila = partidas.iloc[0]
    assert fila["origen"] == "chesscom"
    assert fila["color"] == "negras"          # el usuario no distingue mayúsculas
    assert fila["resultado"] == "derrota"
    assert fila["terminacion"] == "abandono"
    assert fila["reloj"] == "10+0"
    assert fila["eco"] == "C46"
    assert fila["apertura"] == "Three Knights Opening"
    assert (fila["mi_elo"], fila["elo_rival"]) == (812, 800)
    assert jugadas["reloj_restante"].iloc[0] == 598


def test_desarrollo_enroque_y_dama(cache):
    partidas, _ = leer_pgn(PGN_CHESSCOM, cache=cache)
    fila = partidas.iloc[0]
    assert fila["jugada_enroque"] == 10        # 10... O-O
    # Bc5, Nc6 y Nge7 en las primeras 10 (11... Bxh3 ya no cuenta).
    assert fila["menores_desarrolladas"] == 3
    assert fila["dama_temprana"]               # 2... Qf6


def test_sin_enroque_ni_dama(cache):
    texto = pgn_minimate("e4 e5 Nf3 Nc6", color=chess.WHITE)
    partidas, _ = leer_pgn(texto, cache=cache)
    assert partidas.iloc[0]["menores_desarrolladas"] == 1
    assert math.isnan(partidas.iloc[0]["jugada_enroque"])   # nunca enroqué
    assert not partidas.iloc[0]["dama_temprana"]


# --- Tabla de jugadas -------------------------------------------------------------

def test_jugadas_columnas_y_perspectiva(cache):
    _, jugadas = leer_pgn(pgn_minimate(), cache=cache)
    primera = jugadas.iloc[0]
    assert (primera["numero"], primera["color"], primera["es_mia"], primera["san"]) == \
        (1, "blancas", True, "e4")
    assert primera["reloj_restante"] == 180
    assert jugadas.iloc[1]["es_mia"] == False  # noqa: E712
    # Evaluaciones desde MI punto de vista: al final pierdo -> negativas.
    assert jugadas.iloc[-1]["eval_despues"] == -1000       # limitada a -10 peones
    assert jugadas.iloc[-1]["mate_despues"] == 0           # ya es mate
    assert jugadas.iloc[-2]["mate_despues"] == -1          # me dan mate en 1
    # La eval de antes de una jugada es la de después de la anterior.
    assert jugadas.iloc[5]["eval_antes"] == jugadas.iloc[4]["eval_despues"]


def test_perdida_y_clasificacion(cache):
    _, jugadas = leer_pgn(pgn_minimate(), cache=cache)
    mias = jugadas[jugadas["es_mia"]]
    assert (mias["perdida"] >= 0).all()
    # Be2 deja el mate en una: pierde lo máximo (limitado a 10 peones).
    be2 = mias[mias["san"] == "Be2"].iloc[0]
    assert be2["perdida"] > 100 and be2["clasificacion"] in ("error", "error grave")


def test_jugadas_con_negras_perspectiva(cache):
    texto = pgn_minimate("e4 e5 Qh5 Qg5 Qxg5", color=chess.BLACK)
    _, jugadas = leer_pgn(texto, cache=cache)
    qg5 = jugadas[jugadas["san"] == "Qg5"].iloc[0]
    assert qg5["es_mia"] and qg5["clasificacion"] == "error grave"
    assert qg5["eval_despues"] < -500          # desde MI punto de vista (negras): mal
    assert qg5["pieza_colgada"]               # la dama quedó para regalar


def test_fases():
    assert fase_de(chess.Board(), 1) == "apertura"
    assert fase_de(chess.Board(), 11) == "medio juego"
    final = chess.Board("4k3/8/8/8/8/8/R7/4K2R w - - 0 40")   # dos torres
    assert fase_de(final, 40) == "final"


# --- Patrones de principiante ------------------------------------------------------

def test_pieza_colgada():
    # El caballo va a f3, donde lo ataca la dama negra (d5) y nadie lo defiende.
    antes = chess.Board("4k3/8/8/3q4/8/8/8/4K1N1 w - - 0 1")
    assert colgo_pieza(antes, chess.Move.from_uci("g1f3"))
    assert not colgo_pieza(antes, chess.Move.from_uci("g1e2"))   # en e2 lo defiende el rey


def test_un_cambio_no_es_pieza_colgada():
    # Bxc6: el alfil que comió el caballo "queda atacado" por un peón (dxc6),
    # pero es un cambio parejo, no un regalo.
    antes = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4")
    assert not colgo_pieza(antes, chess.Move.from_uci("b5c6"))


def test_pieza_defendida_pero_atacada_por_un_peon():
    # El caballo en e5 está defendido por la dama (h2), pero lo ataca un peón (d6):
    # si blancas juegan otra cosa, el peón lo come y gana material.
    antes = chess.Board("4k3/8/3p4/4N3/8/8/P6Q/4K3 w - - 0 1")
    assert colgo_pieza(antes, chess.Move.from_uci("a2a3"))
    assert not colgo_pieza(antes, chess.Move.from_uci("e5c4"))   # lo saca de ahí


def test_captura_perdida():
    # La dama negra en d5 está sin defensa y la torre blanca la puede comer.
    antes = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    assert dejo_pasar_captura(antes, chess.Move.from_uci("e1e2"))
    assert not dejo_pasar_captura(antes, chess.Move.from_uci("d1d5"))


def test_sin_nada_para_comer_no_es_captura_perdida():
    assert not dejo_pasar_captura(chess.Board(), chess.Move.from_uci("e2e4"))


def test_patrones_solo_en_mis_jugadas(cache):
    _, jugadas = leer_pgn(pgn_minimate(), cache=cache)
    assert jugadas.loc[~jugadas["es_mia"], "pieza_colgada"].isna().all()
    mias = jugadas[jugadas["es_mia"]]
    # 6. Rf1: el caballo podía comer la torre de h8 gratis (Nxh8).
    assert mias[mias["san"] == "Rf1"].iloc[0]["captura_perdida"]


# --- Aperturas y relojes ------------------------------------------------------------

def test_apertura():
    assert clasificar_apertura("e4 c5 Nf3".split()) == ("B20", "Siciliana")
    assert clasificar_apertura("e4 e5 Nf3 Nc6 Bb5 a6".split()) == ("C60", "Ruy López")
    assert clasificar_apertura("h4".split()) == (None, None)


def test_reloj_normalizado():
    assert reloj_normalizado({"TimeControl": "180+2"}) == "3+2"
    assert reloj_normalizado({"TimeControl": "600"}) == "10+0"
    assert reloj_normalizado({"TimeControl": "1/86400"}) == "diaria"
    assert reloj_normalizado({"Reloj": "5+3", "TimeControl": "300+3"}) == "5+3"


# --- Evaluaciones de Chess.com y caché ----------------------------------------------

def test_chesscom_sin_evaluar_queda_vacio(cache):
    _, jugadas = leer_pgn(PGN_CHESSCOM, cache=cache)
    # Sin evaluar (y con la caché vacía) las evaluaciones quedan vacías (NaN).
    assert jugadas["eval_antes"].isna().all()
    assert jugadas["perdida"].isna().all()


def test_chesscom_evaluado_con_cache(tmp_path, monkeypatch):
    ruta = tmp_path / "evaluaciones.parquet"
    llamadas = []
    original = datos.valor_posicion

    def contar(tablero, profundidad=2):
        llamadas.append(tablero.epd())
        return original(tablero, profundidad)

    monkeypatch.setattr(datos, "valor_posicion", contar)
    _, jugadas = leer_pgn(PGN_CHESSCOM, evaluar=True, cache=CacheEvaluaciones(ruta))
    assert jugadas["eval_despues"].notna().all()
    assert ruta.exists()
    primeras = len(llamadas)
    assert primeras > 0

    # Segunda vez (otra caché leída del archivo): no recalcula nada.
    _, otra_vez = leer_pgn(PGN_CHESSCOM, evaluar=True, cache=CacheEvaluaciones(ruta))
    assert len(llamadas) == primeras
    assert otra_vez["eval_despues"].equals(jugadas["eval_despues"])
    # Y sin evaluar=True también usa la caché.
    _, sin_evaluar = leer_pgn(PGN_CHESSCOM, cache=CacheEvaluaciones(ruta))
    assert sin_evaluar["eval_despues"].notna().all()


# --- Las dos fuentes juntas ---------------------------------------------------------

def test_cargar_todo_junta_los_origenes(tmp_path):
    (tmp_path / "partidas.pgn").write_text(pgn_minimate(), encoding="utf-8")
    (tmp_path / "chesscom.pgn").write_text(PGN_CHESSCOM, encoding="utf-8")
    partidas, jugadas = cargar_todo(tmp_path)
    assert sorted(partidas["origen"]) == ["chesscom", "minimate"]
    assert set(jugadas["origen"]) == {"chesscom", "minimate"}
    assert partidas["partida"].is_unique


def test_cargar_todo_sin_datos(tmp_path):
    partidas, jugadas = cargar_todo(tmp_path / "vacia")
    assert partidas.empty and jugadas.empty
    assert "resultado" in partidas.columns and "perdida" in jugadas.columns


def test_fase_de_la_derrota(cache):
    partidas, jugadas = leer_pgn(pgn_minimate(), cache=cache)
    por_fase = fase_de_la_derrota(partidas, jugadas)
    assert list(por_fase.index) == ["apertura", "medio juego", "final"]
    assert por_fase.sum() == 1          # una derrota
    assert por_fase["apertura"] == 1    # todo pasó en la apertura
