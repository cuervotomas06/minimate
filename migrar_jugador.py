# Pasa las partidas de un jugador viejo (de cuando se entraba con un nombre,
# por ejemplo "mantarraya") a tu jugador con cuenta (Google o Lichess).
#
# Uso:
#   python migrar_jugador.py --listar
#       muestra los jugadores, sus cuentas y sus claves
#   python migrar_jugador.py --desde mantarraya --hacia google:123456789012345678901
#       pasa las partidas de "mantarraya" al jugador con esa clave
#
# Tu clave aparece en la app: Mis estadísticas -> Mis cuentas de ajedrez.
# (Hay que haber iniciado sesión al menos una vez, así tu jugador existe.)
#
# Las partidas repetidas no se duplican. El jugador viejo se borra al final.
# Alternativa automática: la sección [migracion] de secrets.toml (ver docs/LOGIN.md).

import argparse
import sys

from src import base_de_datos, cuentas


def listar():
    for jugador in base_de_datos.listar_jugadores():
        suyas = base_de_datos.cuentas_del_jugador(jugador["id"])
        detalle = ", ".join(f"{c['proveedor']} ({c['usuario']})" for c in suyas) or "sin cuentas"
        partidas = len(base_de_datos.claves_guardadas(jugador["id"]))
        print(f"{jugador['clave']:<40} {jugador['nombre']:<25} {partidas:>5} partidas · {detalle}")


def migrar(desde, hacia_clave):
    """Devuelve cuántas partidas movió. Errores con mensaje en ValueError."""
    hacia_id = base_de_datos.buscar_jugador(hacia_clave)
    if hacia_id is None:
        raise ValueError(f"No existe el jugador «{hacia_clave}». ¿Iniciaste sesión al menos "
                         "una vez? (Usá --listar para ver las claves.)")
    try:
        movidas = cuentas.migrar_jugador(desde, hacia_id)
    except cuentas.CuentaDeOtro as error:
        raise ValueError(str(error)) from error
    if movidas is None:
        raise ValueError(f"No hay un jugador «{desde}» para migrar (¿ya se migró?).")
    return movidas


def main():
    parser = argparse.ArgumentParser(description="Pasa partidas de un jugador viejo a tu cuenta.")
    parser.add_argument("--listar", action="store_true", help="mostrar jugadores y claves")
    parser.add_argument("--desde", help="nombre del jugador viejo, por ejemplo mantarraya")
    parser.add_argument("--hacia", help="clave de tu jugador, por ejemplo google:1234...")
    args = parser.parse_args()

    if not base_de_datos.hay_supabase():
        sys.exit("No hay credenciales de Supabase (ver supabase/LEEME.md).")
    try:
        if args.listar:
            listar()
            return
        if not (args.desde and args.hacia):
            sys.exit("Usá --listar, o --desde NOMBRE --hacia CLAVE.")
        movidas = migrar(args.desde, args.hacia)
        print(f"Listo: {movidas} partidas de «{args.desde}» pasaron a {args.hacia}.")
    except ValueError as error:
        sys.exit(str(error))
    except base_de_datos.ErrorBaseDeDatos as error:
        sys.exit(f"Error con Supabase: {error}")


if __name__ == "__main__":
    main()
