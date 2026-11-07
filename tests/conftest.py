# Configuración común de los tests (pytest la carga sola).

import pytest


@pytest.fixture(autouse=True)
def carpeta_de_datos_temporal(tmp_path, monkeypatch):
    """Todos los tests guardan partidas en una carpeta temporal, nunca en la
    carpeta datos/ de verdad. (src/guardado.py lee MINIMATE_DATOS.)"""
    carpeta = tmp_path / "datos"
    monkeypatch.setenv("MINIMATE_DATOS", str(carpeta))
    return carpeta
