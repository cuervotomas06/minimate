# Niveles de dificultad de MiniMate.
#
# Cada nivel es una combinación de:
# - profundidad: cuántas jugadas hacia adelante mira minimax.
# - quietud: si al llegar al final sigue mirando capturas (búsqueda de quietud).
#   Sin quietud el bot "regala" piezas mucho más seguido.
#
# elo: Elo aproximado, redondeado a 50. Medido el 05/11/2026 con
# Stockfish 19 limitado (UCI_LimitStrength, 0,1 s por jugada):
#   Difícil      vs 1320/1500/1700, 30 partidas: 21,5 puntos   -> ~1670
#   Intermedio   vs 1320/1500, 20 partidas: 11 puntos          -> ~1450
#   Fácil        vs 1320, 10 partidas: 2 puntos                -> ~1080
#   Principiante: no se puede medir con Stockfish (mínimo 1320); con
#     medir_niveles.py, Fácil le ganó 18 de 20 (+382)          -> ~700
# Son estimaciones con pocas partidas (±100 o más): sirven para comparar
# niveles, no son un Elo oficial. Para volver a medir: medir_elo.py y
# medir_niveles.py.
#
# Probamos también profundidad 4 con quietud: dio ~1660 (igual que Difícil)
# y tarda unas 8 veces más, así que no lo incluimos como nivel.

NIVELES = {
    "Principiante": {"profundidad": 1, "quietud": False, "elo": 700},
    "Fácil":        {"profundidad": 2, "quietud": False, "elo": 1100},
    "Intermedio":   {"profundidad": 2, "quietud": True,  "elo": 1450},
    "Difícil":      {"profundidad": 3, "quietud": True,  "elo": 1650},
}

NIVEL_POR_DEFECTO = "Intermedio"


def describir(nombre):
    """Texto corto para mostrar debajo del selector."""
    nivel = NIVELES[nombre]
    partes = []
    if nivel["elo"] is not None:
        partes.append(f"≈ {nivel['elo']} Elo")
    jugadas = "jugada" if nivel["profundidad"] == 1 else "jugadas"
    partes.append(f"mira {nivel['profundidad']} {jugadas} adelante")
    partes.append("revisa los cambios de piezas" if nivel["quietud"]
                  else "no revisa los cambios de piezas")
    return " · ".join(partes)
