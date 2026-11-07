# Configuración común de los tests (pytest la carga sola).

import pytest

from src import base_de_datos


@pytest.fixture(autouse=True)
def carpeta_de_datos_temporal(tmp_path, monkeypatch):
    """Todos los tests guardan partidas en una carpeta temporal, nunca en la
    carpeta datos/ de verdad. (src/datos.py lee MINIMATE_DATOS.)"""
    carpeta = tmp_path / "datos"
    monkeypatch.setenv("MINIMATE_DATOS", str(carpeta))
    return carpeta


@pytest.fixture(autouse=True)
def sin_supabase_de_verdad(monkeypatch):
    """Los tests NUNCA se conectan a Supabase, aunque exista un secrets.toml con
    claves reales: sin credenciales y sin base simulada, salvo que un test pida
    la base simulada (fixture "base")."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_CLAVE", raising=False)
    monkeypatch.setattr(base_de_datos, "credenciales", lambda: None)
    base_de_datos.usar_cliente_de_prueba(None)
    # La caché de Streamlit (st.cache_data) vive mientras dure pytest: la
    # vaciamos para que un test no vea los datos de otro.
    import streamlit as st
    st.cache_data.clear()
    yield
    base_de_datos.usar_cliente_de_prueba(None)


@pytest.fixture
def base():
    """Una base de Supabase simulada (en memoria) que la app usa en lugar de la real."""
    from tests.supabase_falso import SupabaseFalso
    falsa = SupabaseFalso()
    base_de_datos.usar_cliente_de_prueba(falsa)
    return falsa
