# Niveles de dificultad de MiniMate.
#
# Cada nivel dice cómo piensa el bot:
# - tiempo: cuántos segundos piensa por jugada (como mucho). Con reloj puede
#   pensar menos, si le queda poco tiempo (ver src/reloj.py).
# - profundidad_maxima: tope de jugadas hacia adelante (None = sin tope: hasta
#   donde llegue en ese tiempo).
# - quietud: si al llegar al final sigue mirando capturas (búsqueda de quietud).
# - motor: "basico" (la búsqueda de siempre, a profundidad fija) o "completo"
#   (src/busqueda.py con todas las mejoras: tabla de transposiciones, killers,
#   evaluación de finales; la versión exacta es VERSION_FINAL, más abajo).
#
# Los dos primeros son a propósito débiles: profundidad fija, sin quietud y con
# el motor básico. Son EXACTAMENTE los de antes (hay un test que lo comprueba),
# así que su Elo medido sigue valiendo.
#
# elo: medido contra Stockfish 19 limitado (UCI_LimitStrength, 0,1 s por
# jugada) con medir_elo.py, 96 partidas por nivel, en una notebook con AMD
# Ryzen AI 7 350, enchufada, 4 partidas a la vez (unas 10.500 posiciones por
# segundo). None = todavía sin medir.
# Ojo: los niveles por tiempo dependen de la velocidad del procesador. En
# Streamlit Cloud (más lento) llegan menos profundo y juegan algo más débil.

from src.busqueda import BASICA, VERSIONES, Buscador, con_opciones

# Versión del motor nuevo que usan los niveles "completo". v4: sin jugada nula
# ni LMR, porque v5 (con las dos) no le ganó a v4 en partidas (ver README).
VERSION_FINAL = "v4"

NIVELES = {
    "Principiante": {"tiempo": 0.5, "profundidad_maxima": 1, "quietud": False,
                     "motor": "basico", "elo": 700},
    "Fácil":        {"tiempo": 1.0, "profundidad_maxima": 2, "quietud": False,
                     "motor": "basico", "elo": 1100},
    "Intermedio":   {"tiempo": 0.3, "profundidad_maxima": None, "quietud": True,
                     "motor": "completo", "elo": 1580},     # medido: 1582 ± 81
    "Difícil":      {"tiempo": 1.0, "profundidad_maxima": None, "quietud": True,
                     "motor": "completo", "elo": 1740},     # medido: 1735 ± 85
    "Experto":      {"tiempo": 3.0, "profundidad_maxima": None, "quietud": True,
                     "motor": "completo", "elo": 1900},     # medido: 1897 ± 85
}

NIVEL_POR_DEFECTO = "Intermedio"


def opciones_del_nivel(nivel):
    """Las Opciones de búsqueda (src/busqueda.py) de un nivel."""
    if nivel["motor"] == "basico":
        # Sin profundización iterativa: busca directo a su profundidad, igual que antes.
        return con_opciones(BASICA, iterativa=False, con_quietud=nivel["quietud"])
    return con_opciones(VERSIONES[VERSION_FINAL], con_quietud=nivel["quietud"])


def crear_buscador(nombre):
    return Buscador(opciones_del_nivel(NIVELES[nombre]))


def describir(nombre):
    """Texto corto para mostrar debajo del selector."""
    nivel = NIVELES[nombre]
    partes = [f"≈ {nivel['elo']} Elo" if nivel["elo"] is not None else "Elo por medir"]
    if nivel["profundidad_maxima"] is not None:
        jugadas = "jugada" if nivel["profundidad_maxima"] == 1 else "jugadas"
        partes.append(f"mira {nivel['profundidad_maxima']} {jugadas} adelante")
    else:
        partes.append(f"piensa hasta {nivel['tiempo']:g} s por jugada")
    partes.append("revisa los cambios de piezas" if nivel["quietud"]
                  else "no revisa los cambios de piezas")
    return " · ".join(partes)
