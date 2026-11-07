# Sube a Supabase lo que ya tenés guardado en archivos, en datos/:
#   - datos/partidas.pgn     (partidas jugadas en MiniMate)
#   - datos/chesscom.pgn     (partidas importadas de Chess.com)
#   - datos/evaluaciones.parquet (la caché de evaluaciones)
#
# Uso:
#   python subir_a_supabase.py --jugador "Tomás"
#
# --jugador es para las partidas viejas que no dicen de quién son (las nuevas
# traen el encabezado "Jugador" y van a esa persona).
#
# Se puede correr las veces que quieras: las partidas que ya están en Supabase
# no se duplican (cada una tiene una "clave": el link de Chess.com, o un
# resumen de fecha + jugadas para las de MiniMate).
#
# Necesita las credenciales de Supabase en .streamlit/secrets.toml (o en las
# variables de entorno SUPABASE_URL y SUPABASE_CLAVE).

import argparse
import sys
from pathlib import Path

from src import base_de_datos
from src.datos import (ARCHIVO_CACHE, ARCHIVO_CHESSCOM, ARCHIVO_PARTIDAS, CacheEvaluaciones,
                       carpeta_datos)
from src.guardado import subir_partidas
from src.jugador import clave_del_nombre, normalizar_nombre


def subir_todo(jugador, carpeta=None, al_avanzar=None):
    """Sube las partidas y la caché. Devuelve un resumen:
    {"partidas.pgn": (nuevas, repetidas), "chesscom.pgn": (...), "evaluaciones": cantidad}."""
    carpeta = Path(carpeta) if carpeta is not None else carpeta_datos()
    nombre = normalizar_nombre(jugador)
    jugador_id = base_de_datos.id_del_jugador(nombre, clave_del_nombre(nombre))
    # Las que ese jugador ya tiene, para no volver a analizarlas.
    ya = {(clave_del_nombre(nombre), c) for c in base_de_datos.claves_guardadas(jugador_id)}
    # La caché local sirve para completar evaluaciones de Chess.com al subir.
    cache = CacheEvaluaciones(carpeta / ARCHIVO_CACHE)

    resumen = {}
    for archivo, origen in [(ARCHIVO_PARTIDAS, "minimate"), (ARCHIVO_CHESSCOM, "chesscom")]:
        ruta = carpeta / archivo
        if not ruta.exists():
            continue
        avance = (lambda hechas, total, archivo=archivo: al_avanzar(archivo, hechas, total)) \
            if al_avanzar else None
        resumen[archivo] = subir_partidas(ruta.read_text(encoding="utf-8"), origen=origen,
                                          cache=cache, ya_guardadas=ya, al_avanzar=avance,
                                          jugador_si_falta=nombre)

    # La caché de evaluaciones (subirla de nuevo no duplica: reemplaza).
    if cache.valores:
        base_de_datos.guardar_evaluaciones(cache.valores)
    resumen["evaluaciones"] = len(cache.valores)
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Sube a Supabase las partidas de datos/.")
    parser.add_argument("--jugador", required=True,
                        help="tu nombre en MiniMate (para las partidas que no lo dicen)")
    args = parser.parse_args()

    if not base_de_datos.hay_supabase():
        sys.exit("No hay credenciales de Supabase: completá .streamlit/secrets.toml "
                 "(ver supabase/LEEME.md).")
    try:
        resumen = subir_todo(args.jugador, al_avanzar=lambda archivo, hechas, total: print(
            f"  {archivo}: {hechas}/{total}", end="\r"))
    except base_de_datos.ErrorBaseDeDatos as error:
        sys.exit(f"\nError con Supabase: {error}\n(Lo que ya se subió quedó guardado; "
                 "podés volver a correr el script.)")
    print()
    for archivo, valor in resumen.items():
        if archivo == "evaluaciones":
            print(f"Caché de evaluaciones: {valor} posiciones subidas.")
        else:
            print(f"{archivo}: {valor[0]} nuevas, {valor[1]} ya estaban.")


if __name__ == "__main__":
    main()
