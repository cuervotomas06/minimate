# Reloj de ajedrez: controles de tiempo y cuánto puede pensar MiniMate.
#
# Notación "5+3": 5 minutos para toda la partida, y 3 segundos más
# ("incremento") cada vez que hacés una jugada.

# Opciones del selector de la app: nombre -> (segundos iniciales, incremento).
CONTROLES = {
    "Sin reloj": None,
    "3+2": (3 * 60, 2),
    "5+3": (5 * 60, 3),
    "10+5": (10 * 60, 5),
    "15+10": (15 * 60, 10),
}
CONTROL_POR_DEFECTO = "Sin reloj"

# Cuánto tarda MiniMate en una jugada, en segundos, según la profundidad y si
# usa quietud. Medido en 80 posiciones de partidas reales (05/11/2026):
#   prof. 2 con quietud: promedio 0,06 s, el 90% en menos de 0,16 s
#   prof. 3 con quietud: promedio 0,40 s, el 90% en menos de 1,1 s (máx. 2,9 s)
# Usamos el "90%" multiplicado por ~3, porque en Streamlit Cloud el
# procesador es más lento que en una compu común.
TIEMPO_ESTIMADO = {
    (1, False): 0.02,
    (1, True): 0.1,
    (2, False): 0.1,
    (2, True): 0.5,
    (3, False): 1.0,
    (3, True): 3.0,
}

# Suponemos que quedan unas 30 jugadas por hacer.
JUGADAS_POR_DELANTE = 30


def tiempo_para_esta_jugada(restante, incremento):
    """Cuántos segundos puede usar MiniMate en esta jugada.
    Repartimos lo que queda entre las jugadas que faltan, más casi todo el
    incremento (que se recupera al jugar). Nunca más de la mitad de lo que queda."""
    presupuesto = restante / JUGADAS_POR_DELANTE + incremento * 0.8
    return min(presupuesto, restante / 2)


def profundidad_segun_reloj(profundidad, con_quietud, restante, incremento):
    """La profundidad del nivel, o menos si no le alcanza el tiempo.
    Bajamos de a una hasta que lo estimado entre en el presupuesto.
    Profundidad 1 es lo mínimo: alguna jugada tiene que hacer."""
    presupuesto = tiempo_para_esta_jugada(restante, incremento)
    while profundidad > 1 and TIEMPO_ESTIMADO[(profundidad, con_quietud)] > presupuesto:
        profundidad -= 1
    return profundidad
