# Baja todas tus partidas de Chess.com y las guarda en datos/chesscom.pgn.
#
# Usa la API pública de Chess.com (sin claves ni login):
#   https://api.chess.com/pub/player/<usuario>/games/archives
#       -> la lista de "archivos mensuales" (uno por cada mes en que jugaste)
#   https://api.chess.com/pub/player/<usuario>/games/2026/11
#       -> las partidas de ese mes, cada una con su PGN
# Chess.com pide que cada programa se identifique con un User-Agent propio.
#
# Uso:
#   python importar_chesscom.py --usuario TU_USUARIO
#   python importar_chesscom.py --usuario TU_USUARIO --meses 3   (solo los últimos 3 meses)
#   python importar_chesscom.py --evaluar                          (evaluar con MiniMate)
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

from src.datos import ARCHIVO_CHESSCOM, CacheEvaluaciones, leer_pgn
from src.guardado import carpeta_datos

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


def marcar(pgn, usuario):
    """Agrega dos encabezados propios: de dónde viene y cuál es tu usuario
    (así src/datos.py sabe con qué color jugaste)."""
    return f'[Origen "chesscom"]\n[MiUsuario "{usuario}"]\n' + pgn.lstrip()


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


def importar(usuario, ruta, meses=None, pedir=pedir_json, al_avanzar=None):
    """Baja las partidas, las junta con las que ya estaban y escribe el archivo.
    Devuelve (nuevas, total)."""
    partidas = leer_existentes(ruta)
    antes = len(partidas)
    for pgn in bajar_partidas(usuario, meses, pedir, al_avanzar):
        partidas.setdefault(clave(pgn), marcar(pgn, usuario))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n\n".join(p.strip() for p in partidas.values()) + "\n", encoding="utf-8")
    return len(partidas) - antes, len(partidas)


def main():
    parser = argparse.ArgumentParser(description="Importa tus partidas de Chess.com.")
    parser.add_argument("--usuario", default=USUARIO, help="tu usuario de Chess.com")
    parser.add_argument("--meses", type=int, default=None,
                        help="solo los últimos N meses (por defecto, todos)")
    parser.add_argument("--evaluar", action="store_true",
                        help="después de bajar, evaluar las posiciones con MiniMate (tarda)")
    parser.add_argument("--sin-bajar", action="store_true",
                        help="no bajar nada (por ejemplo, para solo --evaluar)")
    args = parser.parse_args()

    ruta = carpeta_datos() / ARCHIVO_CHESSCOM

    if not args.sin_bajar:
        if args.usuario == "TU_USUARIO":
            sys.exit("Falta tu usuario: python importar_chesscom.py --usuario TU_USUARIO "
                     "(o cambiá USUARIO al principio de este archivo).")
        print(f"Bajando las partidas de {args.usuario}...")
        try:
            nuevas, total = importar(
                args.usuario, ruta, args.meses,
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


if __name__ == "__main__":
    main()
