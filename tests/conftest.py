# Configuración común de los tests (pytest la carga sola).
#
# Ningún test usa servicios de verdad: Supabase, Google, Lichess y Chess.com
# están simulados. Si un test se olvida de simular algo, falla en vez de
# conectarse a internet.

import pytest

from src import base_de_datos, chesscom, cuentas, lichess

USUARIO_DE_PRUEBA = {
    "proveedor": "google", "id": "sub-prueba-0001", "nombre": "Persona de Prueba",
    "foto": None, "email": "prueba@example.com", "email_verificado": True,
}


@pytest.fixture(autouse=True)
def carpeta_de_datos_temporal(tmp_path, monkeypatch):
    """Todos los tests guardan partidas en una carpeta temporal, nunca en la
    carpeta datos/ de verdad. (src/datos.py lee MINIMATE_DATOS.)"""
    carpeta = tmp_path / "datos"
    monkeypatch.setenv("MINIMATE_DATOS", str(carpeta))
    return carpeta


@pytest.fixture(autouse=True)
def sin_servicios_de_verdad(monkeypatch):
    """Los tests NUNCA se conectan a Supabase, Google, Lichess ni Chess.com,
    aunque exista un secrets.toml con claves reales."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_CLAVE", raising=False)
    monkeypatch.setattr(base_de_datos, "credenciales", lambda: None)
    base_de_datos.usar_cliente_de_prueba(None)
    # Sin sesión de Google (los tests que la necesitan usan el fixture "google").
    monkeypatch.setattr(cuentas, "usuario_google", lambda: None)
    monkeypatch.setattr(cuentas, "google_configurado", lambda: False)
    monkeypatch.setattr(cuentas, "migracion_configurada", lambda: None)

    def sin_internet(*args, **kwargs):
        raise AssertionError("Un test intentó conectarse a internet")

    monkeypatch.setattr(chesscom, "pedir_json", sin_internet)
    monkeypatch.setattr(lichess.ClienteHttp, "_pedido", sin_internet)
    lichess._pendientes.clear()
    # La caché de Streamlit (st.cache_data) vive mientras dure pytest: la
    # vaciamos para que un test no vea los datos de otro.
    import streamlit as st
    st.cache_data.clear()
    yield
    base_de_datos.usar_cliente_de_prueba(None)
    lichess._pendientes.clear()


@pytest.fixture
def base():
    """Una base de Supabase simulada (en memoria) que la app usa en lugar de la real."""
    from tests.supabase_falso import SupabaseFalso
    falsa = SupabaseFalso()
    base_de_datos.usar_cliente_de_prueba(falsa)
    return falsa


class GoogleFalso:
    """Simula st.user: google.entrar() inicia sesión, google.salir() la cierra."""

    def __init__(self):
        self.usuario = None

    def entrar(self, **cambios):
        self.usuario = {**USUARIO_DE_PRUEBA, **cambios}
        return self.usuario

    def salir(self):
        self.usuario = None


@pytest.fixture
def google(monkeypatch):
    falso = GoogleFalso()
    monkeypatch.setattr(cuentas, "usuario_google",
                        lambda: dict(falso.usuario) if falso.usuario else None)
    return falso
