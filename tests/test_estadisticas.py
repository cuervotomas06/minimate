# Tests de la página "Mis estadísticas" (paginas/estadisticas.py) con AppTest.
# Se corren con: pytest

from streamlit.testing.v1 import AppTest

from tests.test_datos import PGN_CHESSCOM, pgn_minimate

RUTA_PAGINA = "../paginas/estadisticas.py"


def test_sin_datos_explica_como_empezar(carpeta_de_datos_temporal):
    at = AppTest.from_file(RUTA_PAGINA, default_timeout=60).run()
    assert not at.exception
    assert "Cómo empezar" in at.info[0].value
    assert "importar_chesscom.py" in at.info[0].value


def test_con_datos_muestra_las_estadisticas(carpeta_de_datos_temporal):
    carpeta_de_datos_temporal.mkdir(parents=True)
    (carpeta_de_datos_temporal / "partidas.pgn").write_text(pgn_minimate(), encoding="utf-8")
    (carpeta_de_datos_temporal / "chesscom.pgn").write_text(PGN_CHESSCOM, encoding="utf-8")
    at = AppTest.from_file(RUTA_PAGINA, default_timeout=60).run()
    assert not at.exception
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["Partidas jugadas"] == "2"
    assert metricas["Victorias con blancas"] == "0%"   # la de MiniMate (perdí con blancas)
    assert metricas["Victorias con negras"] == "0%"    # la de Chess.com (perdí con negras)
    titulos = [s.value for s in at.subheader]
    assert "¿En qué fase pierdo la partida?" in titulos
    assert "Tus 5 errores graves más recientes" in titulos
    # La de Chess.com no está evaluada: avisa cómo calcularlo.
    assert any("--evaluar" in c.value for c in at.caption)


def test_filtrar_por_origen(carpeta_de_datos_temporal):
    carpeta_de_datos_temporal.mkdir(parents=True)
    (carpeta_de_datos_temporal / "partidas.pgn").write_text(pgn_minimate(), encoding="utf-8")
    (carpeta_de_datos_temporal / "chesscom.pgn").write_text(PGN_CHESSCOM, encoding="utf-8")
    at = AppTest.from_file(RUTA_PAGINA, default_timeout=60).run()
    at.multiselect[0].set_value(["minimate"]).run()
    assert {m.label: m.value for m in at.metric}["Partidas jugadas"] == "1"
