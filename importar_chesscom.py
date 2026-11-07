# Baja tus partidas de Chess.com y las guarda:
# - en Supabase, si hay credenciales: SOLO si la cuenta está vinculada y
#   verificada en la app (Mis estadísticas -> Mis cuentas de ajedrez), y van
#   al jugador dueño de esa cuenta;
# - si no, en datos/chesscom.pgn.
# (Desde la app también se puede importar, con el botón "Actualizar".)
#
# Usa la API pública de Chess.com (sin claves ni login), ver src/chesscom.py.
#
# Uso:
#   python importar_chesscom.py --usuario TU_USUARIO
#   python importar_chesscom.py --usuario TU_USUARIO --meses 3     (solo los últimos 3 meses)
#   python importar_chesscom.py --usuario TU_USUARIO --sin-bajar --evaluar   (evaluar con MiniMate)
#
# Se puede correr varias veces: las partidas que ya estaban no se duplican
# (se reconocen por su link).

import argparse
import io
import re
import sys
import time

import chess.pgn

from src import base_de_datos, importar as importacion
from src.chesscom import (URL_ARCHIVOS, USER_AGENT, UsuarioNoEncontrado,  # noqa: F401
                          bajar_partidas, pedir_json, perfil)
from src.datos import ARCHIVO_CHESSCOM, CacheEvaluaciones, carpeta_datos, leer_pgn
from src.jugador import normalizar_nombre

# Tu usuario de Chess.com (o pasalo con --usuario).
USUARIO = "TU_USUARIO"


def marcar(pgn, usuario, jugador=None):
    """Agrega encabezados propios: de dónde viene, cuál es tu usuario (así
    src/datos.py sabe con qué color jugaste) y tu nombre en MiniMate."""
    extra = f'[Jugador "{normalizar_nombre(jugador)}"]\n' if jugador else ""
    return f'[Origen "chesscom"]\n[MiUsuario "{usuario}"]\n' + extra + pgn.lstrip()


def clave(pgn):
    """El link de la partida (único para cada una), o el texto entero si no tiene."""
    coincidencia = re.search(r'\[Link "([^"]+)"\]', pgn)
    return coincidencia.group(1) if coincidencia else pgn


def leer_existentes(ruta):
    """{link: pgn} de las partidas que ya estaban guardadas."""
    if not ruta.exists():
        return {}
    existentes = {}
    lector = io.StringIO(ruta.read_text(encoding="utf-8"))
    while (juego := chess.pgn.read_game(lector)) is not None:
        texto = str(juego)
        existentes[clave(texto)] = texto
    return existentes


def importar(usuario, ruta, meses=None, pedir=pedir_json, al_avanzar=None, jugador=None):
    """Baja las partidas, las junta con las que ya estaban y escribe el archivo.
    Devuelve (nuevas, total)."""
    partidas = leer_existentes(ruta)
    antes = len(partidas)
    for pgn in bajar_partidas(usuario, meses, pedir, al_avanzar):
        partidas.setdefault(clave(pgn), marcar(pgn, usuario, jugador))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n\n".join(p.strip() for p in partidas.values()) + "\n", encoding="utf-8")
    return len(partidas) - antes, len(partidas)


def cuenta_vinculada(usuario, pedir=None):
    """La cuenta de Chess.com vinculada y verificada en la app, o None.
    Se busca por el player_id (no cambia aunque cambies de usuario)."""
    datos = perfil(usuario, pedir)
    cuenta = base_de_datos.buscar_cuenta("chesscom", str(datos["player_id"]))
    if cuenta is None or not cuenta.get("verificado"):
        return None
    return cuenta


def main():
    parser = argparse.ArgumentParser(description="Importa tus partidas de Chess.com.")
    parser.add_argument("--usuario", default=USUARIO, help="tu usuario de Chess.com")
    parser.add_argument("--meses", type=int, default=None,
                        help="solo los últimos N meses (por defecto, todos)")
    parser.add_argument("--evaluar", action="store_true",
                        help="después de bajar, evaluar las posiciones con MiniMate (tarda)")
    parser.add_argument("--sin-bajar", action="store_true",
                        help="no bajar nada (por ejemplo, para solo --evaluar)")
    parser.add_argument("--jugador", default=None,
                        help="(sin Supabase) tu nombre, para el encabezado Jugador")
    args = parser.parse_args()

    if base_de_datos.hay_supabase():
        main_supabase(args)
        return

    ruta = carpeta_datos() / ARCHIVO_CHESSCOM

    if not args.sin_bajar:
        if args.usuario == "TU_USUARIO":
            sys.exit("Falta tu usuario: python importar_chesscom.py --usuario TU_USUARIO "
                     "(o cambiá USUARIO al principio de este archivo).")
        print(f"Bajando las partidas de {args.usuario}...")
        try:
            nuevas, total = importar(
                args.usuario, ruta, args.meses, jugador=args.jugador,
                al_avanzar=lambda hechos, todos: print(f"  mes {hechos}/{todos}", end="\r"))
        except UsuarioNoEncontrado:
            sys.exit(f"Chess.com no encontró el usuario «{args.usuario}».")
        print(f"\n{nuevas} partidas nuevas, {total} en total, en {ruta}")

    if args.evaluar:
        # Las partidas de Chess.com no traen evaluación: la calcula MiniMate
        # (profundidad 2 con quietud) y la guarda en datos/evaluaciones.parquet.
        print("Evaluando posiciones con MiniMate (la primera vez tarda; después usa la caché)...")
        cache = CacheEvaluaciones()
        inicio = time.time()
        leer_pgn(ruta, origen="chesscom", evaluar=True, cache=cache,
                 al_avanzar=lambda hechas, todas: print(
                     f"  partida {hechas}/{todas} ({time.time() - inicio:.0f} s)", end="\r"))
        print(f"\nListo: {len(cache.valores)} posiciones evaluadas en la caché.")


def main_supabase(args):
    """Con Supabase: solo cuentas vinculadas y verificadas en la app."""
    if args.usuario == "TU_USUARIO":
        sys.exit("Falta tu usuario: python importar_chesscom.py --usuario TU_USUARIO "
                 "(o cambiá USUARIO al principio de este archivo).")
    try:
        cuenta = cuenta_vinculada(args.usuario)
        if cuenta is None:
            sys.exit(f"La cuenta «{args.usuario}» no está vinculada y verificada en MiniMate. "
                     "Vinculala desde la app: Mis estadísticas -> Mis cuentas de ajedrez.")
        if not args.sin_bajar:
            print(f"Bajando las partidas de {args.usuario} y subiéndolas a Supabase...")
            nuevas, repetidas = importacion.importar_cuenta(
                cuenta, args.meses, maximo=None, evaluar=False,
                al_avanzar=lambda hechas, todas: print(f"  partida {hechas}/{todas}", end="\r"))
            print(f"\n{nuevas} partidas nuevas, {repetidas} ya estaban.")
        if args.evaluar:
            print("Evaluando con MiniMate las jugadas sin evaluación (la caché queda en Supabase)...")
            inicio = time.time()
            cantidad = importacion.evaluar_pendientes(
                cuenta["jugador_id"], "chesscom",
                al_avanzar=lambda hechas, todas: print(
                    f"  partida {hechas}/{todas} ({time.time() - inicio:.0f} s)", end="\r"))
            print(f"\nListo: {cantidad} partidas actualizadas.")
    except UsuarioNoEncontrado:
        sys.exit(f"Chess.com no encontró el usuario «{args.usuario}».")
    except base_de_datos.ErrorBaseDeDatos as error:
        sys.exit(f"Error con Supabase: {error}")


if __name__ == "__main__":
    main()
