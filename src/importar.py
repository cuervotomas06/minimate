# Importar partidas de cuentas vinculadas (Chess.com y Lichess) a Supabase.
#
# Lo usan la página "Mis estadísticas" (botón Actualizar) y el script
# importar_chesscom.py. Reglas:
# - solo cuentas vinculadas Y verificadas (ver src/cuentas.py);
# - las partidas van al jugador dueño de la cuenta (nunca a otro);
# - sin duplicados (cada partida tiene su clave: el link);
# - las evaluaciones usan la caché de Supabase (una posición se calcula una vez).

from src import base_de_datos, chesscom, lichess
from src.datos import CacheSupabase, filas_para_base, leer_pgn
from src.guardado import subir_partidas

MESES = (1, 3, 6)          # opciones de la app
MAXIMO_PARTIDAS = 100      # como mucho, las 100 más recientes por vez


class CuentaNoVerificada(Exception):
    pass


def marcar(pgn, origen, usuario):
    """Agrega encabezados propios: de dónde viene y cuál es tu usuario allá
    (así src/datos.py sabe con qué color jugaste)."""
    return f'[Origen "{origen}"]\n[MiUsuario "{usuario}"]\n' + pgn.lstrip()


def bajar(cuenta, meses=None, maximo=MAXIMO_PARTIDAS, pedir=None, http=None, al_avanzar=None):
    """PGN de las partidas de la cuenta (las más recientes, hasta 'maximo')."""
    usuario = cuenta["usuario"]
    if cuenta["proveedor"] == "chesscom":
        pgns = chesscom.bajar_partidas(usuario, meses, pedir or chesscom.pedir_json,
                                       al_avanzar=al_avanzar, maximo=maximo)
    elif cuenta["proveedor"] == "lichess":
        pgns = lichess.bajar_partidas(usuario, meses, maximo, http=http)
    else:
        raise ValueError(f"No se pueden importar partidas de {cuenta['proveedor']}.")
    return [marcar(pgn, cuenta["proveedor"], usuario) for pgn in pgns]


def importar_cuenta(cuenta, meses=1, maximo=MAXIMO_PARTIDAS, evaluar=True, al_avanzar=None,
                    pedir=None, http=None):
    """Baja las partidas de una cuenta vinculada y sube las nuevas al jugador
    dueño de la cuenta. Con evaluar=True las analiza con MiniMate (con la
    caché). Devuelve (nuevas, repetidas)."""
    if not cuenta.get("verificado"):
        raise CuentaNoVerificada("Solo se pueden importar partidas de cuentas verificadas.")
    jugador_id = cuenta["jugador_id"]
    pgns = bajar(cuenta, meses, maximo, pedir=pedir, http=http)
    if not pgns:
        return 0, 0
    # Las que el jugador ya tiene no se vuelven a analizar.
    ya = {(jugador_id, clave) for clave in base_de_datos.claves_guardadas(jugador_id)}
    cache = CacheSupabase()
    resultado = subir_partidas("\n\n".join(pgns), jugador_id=jugador_id,
                               origen=cuenta["proveedor"], cache=cache, evaluar=evaluar,
                               ya_guardadas=ya, al_avanzar=al_avanzar)
    cache.guardar()
    return resultado


def evaluar_pendientes(jugador_id, origen, al_avanzar=None):
    """Evalúa con MiniMate las partidas del jugador (de ese origen) que tienen
    jugadas sin evaluación, y actualiza sus jugadas. Devuelve cuántas partidas."""
    pendientes = base_de_datos.partidas_sin_evaluar(jugador_id, origen)
    cache = CacheSupabase()
    for numero, (partida_id, pgn) in enumerate(pendientes, start=1):
        partidas, jugadas = leer_pgn(pgn, origen=origen, evaluar=True, cache=cache,
                                     con_pgn=True)
        for _, filas_jugadas in filas_para_base(partidas, jugadas):
            base_de_datos.actualizar_jugadas(
                [{**fila, "partida_id": partida_id} for fila in filas_jugadas])
        if al_avanzar is not None:
            al_avanzar(numero, len(pendientes))
    cache.guardar()
    return len(pendientes)
