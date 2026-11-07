# Tests de importar_chesscom.py, con una API falsa (sin internet).
# Se corren con: pytest

import importar_chesscom as imp
from src.datos import leer_pgn

ARCHIVOS = {"archives": [
    "https://api.chess.com/pub/player/yo/games/2026/09",
    "https://api.chess.com/pub/player/yo/games/2026/10",
]}


def pgn(numero, blancas="yo", negras="rival", resultado="1-0"):
    return (f'[Event "Live Chess"]\n[Site "Chess.com"]\n[Date "2026.10.0{numero}"]\n'
            f'[White "{blancas}"]\n[Black "{negras}"]\n[Result "{resultado}"]\n'
            f'[TimeControl "180+2"]\n[Link "https://www.chess.com/game/live/{numero}"]\n\n'
            f'1. e4 {{[%clk 0:03:00]}} 1... e5 {{[%clk 0:03:00]}} {resultado}\n')


MESES = {
    ARCHIVOS["archives"][0]: {"games": [
        {"rules": "chess", "pgn": pgn(1)},
        {"rules": "chess960", "pgn": pgn(9)},          # variante: no se importa
    ]},
    ARCHIVOS["archives"][1]: {"games": [
        {"rules": "chess", "pgn": pgn(2, blancas="rival", negras="yo", resultado="1-0")},
    ]},
}


def api_falsa(pedidos):
    def pedir(url):
        pedidos.append(url)
        if url.endswith("/archives"):
            return ARCHIVOS
        return MESES[url]
    return pedir


def test_baja_solo_ajedrez_normal(monkeypatch):
    monkeypatch.setattr(imp.time, "sleep", lambda segundos: None)
    pedidos = []
    pgns = imp.bajar_partidas("Yo", pedir=api_falsa(pedidos))
    assert len(pgns) == 2
    assert pedidos[0] == "https://api.chess.com/pub/player/yo/games/archives"  # en minúscula


def test_solo_los_ultimos_meses(monkeypatch):
    monkeypatch.setattr(imp.time, "sleep", lambda segundos: None)
    pedidos = []
    pgns = imp.bajar_partidas("yo", meses=1, pedir=api_falsa(pedidos))
    assert len(pgns) == 1
    assert pedidos[-1].endswith("/2026/10")


def test_importar_no_duplica_y_se_lee(tmp_path, monkeypatch):
    monkeypatch.setattr(imp.time, "sleep", lambda segundos: None)
    ruta = tmp_path / "chesscom.pgn"
    assert imp.importar("yo", ruta, pedir=api_falsa([])) == (2, 2)
    # Segunda vez: las mismas partidas no se agregan de nuevo.
    assert imp.importar("yo", ruta, pedir=api_falsa([])) == (0, 2)

    partidas, _ = leer_pgn(ruta)
    assert list(partidas["origen"]) == ["chesscom", "chesscom"]
    assert list(partidas["color"]) == ["blancas", "negras"]      # sale de MiUsuario
    assert list(partidas["resultado"]) == ["victoria", "derrota"]
    assert list(partidas["reloj"]) == ["3+2", "3+2"]


def test_user_agent_identifica_el_proyecto():
    assert "MiniMate" in imp.USER_AGENT
    assert "@" not in imp.USER_AGENT   # sin datos personales
