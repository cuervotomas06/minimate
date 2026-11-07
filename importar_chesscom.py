# Baja todas tus partidas de Chess.com y las guarda:
# - en Supabase, si hay credenciales (ver src/base_de_datos.py);
# - si no, en datos/chesscom.pgn.
#
# Usa la API pública de Chess.com (sin claves ni login):
#   https://api.chess.com/pub/player/<usuario>/games/archives
#       -> la lista de "archivos mensuales" (uno por cada mes en que jugaste)
#   https://api.chess.com/pub/player/<usuario>/games/2026/11
#       -> las partidas de ese mes, cada una con su PGN
# Chess.com pide que cada programa se identifique con un User-Agent propio.
#
# Uso (--jugador es tu nombre en MiniMate; con Supabase es obligatorio):
#   python importar_chesscom.py --usuario TU_USUARIO --jugador "Tomás"
#   python importar_chesscom.py --usuario TU_USUARIO --jugador "Tomás" --meses 3
#   python importar_chesscom.py --sin-bajar --jugador "Tomás" --evaluar   (evaluar con MiniMate)
#
# Se puede correr varias veces: las partidas que ya estaban no se duplican
# (se reconocen por su link).

import argparse
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import chess.pgn

from src import base_de_datos
from src.datos import (ARCHIVO_CHESSCOM, CacheEvaluaciones, CacheSupabase, carpeta_datos,
                       filas_para_base, leer_pgn)
from src.guardado import subir_partidas
from src.jugador import clave_del_nombre, normalizar_nombre

# Tu usuario de Chess.com (o pasalo con --usuario).
USUARIO = "TU_USUARIO"

URL_ARCHIVOS = "https://api.chess.com/pub/player/{usuario}/games/archives"
USER_AGENT = "MiniMate/1.0 (bot de ajedrez educativo; https://github.com/cuervotomas06/minimate)"


class UsuarioNoEncontrado(Exception):
    pass


def pedir_json(url, intentos=3):
    """Pide una URL de la API y devuelve el JSON. Si Chess.com dice "pará un
    poco" (error 429), espera y vuelve a probar."""
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                  "Accept": "application/json"})
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(pedido, timeout=30) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise UsuarioNoEncontrado(url) from error
            if error.code == 429 and intento < intentos - 1:
                time.sleep(5 * (intento + 1))
                continue
            raise
    raise RuntimeError(f"No se pudo leer {url}")


def bajar_partidas(usuario, meses=None, pedir=pedir_json, al_avanzar=None):
    """Lista de textos PGN de tus partidas (solo ajedrez normal, sin variantes).
    meses: si se pasa, solo los últimos N meses.
    pedir: la función que hace los pedidos (los tests le pasan una falsa)."""
    archivos = pedir(URL_ARCHIVOS.format(usuario=usuario.lower()))["archives"]
    if meses is not None:
        archivos = archivos[-meses:]
    pgns = []
    for numero, url in enumerate(archivos, start=1):
        for partida in pedir(url).get("games", []):
            # rules = "chess" es el ajedrez normal (no Chess960, bughouse, etc.).
            if partida.get("rules") == "chess" and partida.get("pgn"):
                pgns.append(partida["pgn"])
        if al_avanzar is not None:
            al_avanzar(numero, len(archivos))
        time.sleep(0.2)  # sin apuro: de a un pedido por vez, como pide Chess.com
    return pgns


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


def importar_a_supabase(usuario, jugador, meses=None, pedir=pedir_json, al_avanzar=None):
    """Baja las partidas y sube a Supabase las que el jugador todavía no tiene.
    Devuelve (nuevas, repetidas)."""
    nombre = normalizar_nombre(jugador)
    jugador_id = base_de_datos.id_del_jugador(nombre, clave_del_nombre(nombre))
    # Las que ya están no se vuelven a analizar (y la base igual no las duplica).
    ya = {(clave_del_nombre(nombre), c)
          for c in base_de_datos.claves_guardadas(jugador_id, "chesscom")}
    pgns = [marcar(pgn, usuario, nombre) for pgn in bajar_partidas(usuario, meses, pedir, al_avanzar)]
    if not pgns:
        return 0, 0
    return subir_partidas("\n\n".join(pgns), nombre, origen="chesscom", ya_guardadas=ya)


def evaluar_en_supabase(jugador, al_avanzar=None):
    """Evalúa con MiniMate las partidas de Chess.com del jugador que tienen
    jugadas sin evaluación, y actualiza sus jugadas en Supabase. La caché de
    evaluaciones también queda en Supabase. Devuelve cuántas partidas actualizó."""
    nombre = normalizar_nombre(jugador)
    jugador_id = base_de_datos.id_del_jugador(nombre, clave_del_nombre(nombre))
    pendientes = base_de_datos.partidas_sin_evaluar(jugador_id)
    cache = CacheSupabase()
    for numero, (partida_id, pgn) in enumerate(pendientes, start=1):
        partidas, jugadas = leer_pgn(pgn, origen="chesscom", evaluar=True, cache=cache,
                                     con_pgn=True)
        for _, filas_jugadas in filas_para_base(partidas, jugadas):
            base_de_datos.actualizar_jugadas(
                [{**fila, "partida_id": partida_id} for fila in filas_jugadas])
        if al_avanzar is not None:
            al_avanzar(numero, len(pendientes))
    cache.guardar()
    return len(pendientes)


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
                        help="tu nombre en MiniMate (con Supabase es obligatorio)")
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
    """Lo mismo que main(), pero leyendo y escribiendo en Supabase."""
    if not args.jugador:
        sys.exit('Con Supabase falta tu nombre en MiniMate: --jugador "Tomás"')
    try:
        if not args.sin_bajar:
            if args.usuario == "TU_USUARIO":
                sys.exit("Falta tu usuario: python importar_chesscom.py --usuario TU_USUARIO "
                         "(o cambiá USUARIO al principio de este archivo).")
            print(f"Bajando las partidas de {args.usuario} y subiéndolas a Supabase...")
            nuevas, repetidas = importar_a_supabase(
                args.usuario, args.jugador, args.meses,
                al_avanzar=lambda hechos, todos: print(f"  mes {hechos}/{todos}", end="\r"))
            print(f"\n{nuevas} partidas nuevas, {repetidas} ya estaban.")
        if args.evaluar:
            print("Evaluando con MiniMate las jugadas sin evaluación (la caché queda en Supabase)...")
            inicio = time.time()
            cantidad = evaluar_en_supabase(
                args.jugador,
                al_avanzar=lambda hechas, todas: print(
                    f"  partida {hechas}/{todas} ({time.time() - inicio:.0f} s)", end="\r"))
            print(f"\nListo: {cantidad} partidas actualizadas.")
    except UsuarioNoEncontrado:
        sys.exit(f"Chess.com no encontró el usuario «{args.usuario}».")
    except base_de_datos.ErrorBaseDeDatos as error:
        sys.exit(f"Error con Supabase: {error}")


if __name__ == "__main__":
    main()
