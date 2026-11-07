# Nombres de jugadores: cómo normalizarlos y compararlos.
#
# Ojo: desde que hay cuentas (src/cuentas.py), un jugador se identifica por su
# cuenta de Google o de Lichess, no por el nombre. El nombre es solo para
# mostrar, y para las partidas viejas, que se guardaban por nombre.

LARGO_MAXIMO = 40


def normalizar_nombre(texto):
    """Saca espacios de más: '  Tomás   Amaya ' -> 'Tomás Amaya'."""
    return " ".join(str(texto or "").split())[:LARGO_MAXIMO]


def clave_del_nombre(texto):
    """Versión para comparar: sin importar mayúsculas ni espacios de más.
    'Tomás' y ' tomás ' son el mismo jugador."""
    return normalizar_nombre(texto).casefold()
