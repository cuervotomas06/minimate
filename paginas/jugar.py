# Página "Jugar" de MiniMate: el tablero contra el bot.
# Se abre con: streamlit run app.py (app.py arma el menú y abre esta página).
#
# Cómo funciona Streamlit (importante para entender este archivo):
# cada vez que tocás algo (un botón, un slider, Enter en un cuadro de texto)
# Streamlit vuelve a correr TODO este archivo de arriba a abajo.
# Por eso el tablero se guarda en st.session_state: es un "diccionario"
# que sobrevive entre una corrida y la siguiente.
#
# El tablero es un componente propio hecho en JavaScript
# (src/componente_tablero/). Seleccionar piezas, ver destinos y arrastrar
# pasa todo en el navegador, sin volver a correr este archivo. Recién cuando
# completás una jugada, el componente nos manda su UCI y la procesamos acá.
# El componente también dibuja la barra de evaluación, los relojes y la
# flecha de la revisión, con los datos que le pasamos desde acá.

import time

import chess
import streamlit as st

from src.analisis import (SIMBOLOS, datos_barra, evaluaciones_de_la_revision, resumen,
                          revisar_partida, texto_contador)
from src.componente_tablero import procesar_valor, tablero_interactivo
from src.evaluacion import VALOR_MATE
from src.base_de_datos import resumir_error
from src.guardado import (armar_pgn, guardar_en_archivo, guardar_partida,
                          nombre_de_archivo)
from src.panel_cuenta import barra_lateral, jugador_actual, preparar_sesion
from src.motor import mejor_jugada
from src.niveles import NIVEL_POR_DEFECTO, NIVELES, describir
from src.reloj import CONTROL_POR_DEFECTO, CONTROLES, profundidad_segun_reloj

st.set_page_config(page_title="MiniMate", page_icon="♟")

# Key fija del componente: con la misma key, Streamlit reutiliza el mismo
# iframe en cada rerun en vez de crear uno nuevo (así no parpadea).
KEY_TABLERO = "tablero_js"


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------

def color_humano():
    """Con qué color jugás en ESTA partida: chess.WHITE o chess.BLACK.
    Sale de "color_partida" (lo que había en el selector al empezarla), no del
    selector: si lo cambiás en medio de una partida, el cambio espera tu
    confirmación y la partida sigue con su color."""
    color = st.session_state.get("color_partida") or st.session_state.color
    return chess.WHITE if color == "Blancas" else chess.BLACK


def control_de_tiempo():
    """(segundos iniciales, incremento) del reloj elegido, o None sin reloj."""
    return CONTROLES[st.session_state.get("control", CONTROL_POR_DEFECTO)]


def hay_reloj():
    return control_de_tiempo() is not None


def en_revision():
    """True mientras estás revisando la partida (el tablero no deja mover)."""
    return st.session_state.revision is not None


def partida_terminada(tablero):
    """Terminó por las reglas (mate, tablas...), porque alguien se quedó sin
    tiempo o porque abandonaste."""
    return (tablero.is_game_over() or st.session_state.perdio_por_tiempo is not None
            or st.session_state.abandono)


def es_mi_turno(tablero):
    return (not partida_terminada(tablero) and not en_revision()
            and tablero.turn == color_humano())


# --- Estado de la sesión ---------------------------------------------------
# Todo lo que la app guarda en st.session_state, con su valor inicial.
# Cada clave se inicializa POR SEPARADO si falta (ver inicializar_estado):
# así una sesión abierta con una versión vieja de la app (que no tenía,
# por ejemplo, el reloj) no se rompe al actualizar el código.
# (Las claves de los widgets de la barra lateral, como "control" o "nivel",
# las crea Streamlit con su valor por defecto: no van acá.)

def valores_iniciales():
    """Valores de una partida nueva. Es una función (y no un diccionario fijo)
    para que cada partida tenga su propio tablero y sus propios diccionarios."""
    return {
        "tablero": chess.Board(),
        "mensaje": "",
        # Evaluación de MiniMate después de cada jugada suya:
        # {cantidad de jugadas hechas: valor}. Sirve para la barra.
        "evaluaciones": {},
        # Reloj: segundos que le quedan a cada uno (None = sin reloj) y para
        # qué reloj se calcularon (para detectar si no coinciden con el elegido).
        "tiempos": None,
        "reloj_de_los_tiempos": None,
        "inicio_turno": time.time(),   # cuándo empezó tu turno
        "perdio_por_tiempo": None,     # color que se quedó sin tiempo
        # Revisión de partida.
        "relojes": [],                 # segundos que le quedaban al que movió, por jugada
        "niveles_usados": [],          # nivel de MiniMate en cada jugada suya
        "abandono": False,             # apretaste "Abandonar"
        # Empezar otra partida en medio de una: primero se pide confirmación.
        "cambio_pendiente": None,      # {"tipo": "nueva"/"color"/"reloj", "valor": ...}
        "nueva_despues": None,         # cambio confirmado: se aplica al guardar esta
        # Guardado: se guarda una sola vez, al terminar.
        "partida_guardada": False,
        "pgn_partida": None,           # texto PGN (para el botón de descarga)
        "ruta_guardado": None,         # dónde se guardó: "Supabase" o la ruta (o None)
        "error_guardado": None,        # si falló Supabase: el error, para mostrarlo
        "respaldo_local": None,        # si falló Supabase: la copia en datos/partidas.pgn
        "como_invitado": False,        # terminó sin sesión iniciada: no se guardó
        "analisis_partida": None,      # análisis de la partida (lo usan el PGN y la revisión)
        "revision": None,              # lista de análisis (None = no estás revisando)
        "evaluaciones_revision": {},   # {cantidad de jugadas: valor} de cada posición
        "revisar_pedido": False,       # apretaste "Revisar partida"
        "indice_revision": 0,          # cuántas jugadas se ven en el tablero
    }


def inicializar_estado():
    """Crea las claves que falten, una por una, sin tocar las que ya están."""
    if "color" not in st.session_state:
        st.session_state.color = "Blancas"
    if "ultimo_id_tablero" not in st.session_state:
        st.session_state.ultimo_id_tablero = None  # id de la última jugada del componente
    for clave, valor in valores_iniciales().items():
        if clave not in st.session_state:
            st.session_state[clave] = valor
    # Color y reloj de la partida actual (los del selector al empezarla).
    if "color_partida" not in st.session_state:
        st.session_state.color_partida = st.session_state.color
    if "control_partida" not in st.session_state:
        st.session_state.control_partida = st.session_state.get("control", CONTROL_POR_DEFECTO)


def nueva_partida():
    """Arranca una partida desde cero, con lo que esté elegido en la barra lateral."""
    for clave, valor in valores_iniciales().items():
        st.session_state[clave] = valor
    st.session_state.color_partida = st.session_state.get("color", "Blancas")
    st.session_state.control_partida = st.session_state.get("control", CONTROL_POR_DEFECTO)
    asegurar_reloj()  # tiempos llenos si hay reloj elegido


# --- Empezar otra partida en medio de una --------------------------------------
# Si ya hiciste al menos una jugada, "Nueva partida" (o cambiar el color o el
# reloj) no la tira a la basura: primero pregunta, y si confirmás la partida
# se guarda como abandonada (perdida por vos) antes de empezar la nueva.

def partida_en_curso():
    """True si la partida no terminó y ya hiciste al menos una jugada."""
    tablero = st.session_state.tablero
    return not partida_terminada(tablero) and ya_jugo(tablero, color_humano())


def pedir_nueva_partida():
    """Botón "Nueva partida"."""
    inicializar_estado()  # ver jugar_humano
    if partida_en_curso():
        st.session_state.cambio_pendiente = {"tipo": "nueva"}
    else:
        nueva_partida()


def al_cambiar_color():
    """Selector de color. Ojo: cuando corre este callback, el selector YA
    cambió. Si hay que confirmar, lo volvemos a dejar como estaba."""
    inicializar_estado()  # ver jugar_humano
    if partida_en_curso():
        st.session_state.cambio_pendiente = {"tipo": "color", "valor": st.session_state.color}
        st.session_state.color = st.session_state.color_partida
    else:
        nueva_partida()


def al_cambiar_reloj():
    """Selector de reloj (igual que el de color)."""
    inicializar_estado()  # ver jugar_humano
    if partida_en_curso():
        st.session_state.cambio_pendiente = {"tipo": "reloj", "valor": st.session_state.control}
        st.session_state.control = st.session_state.control_partida
    else:
        nueva_partida()


def confirmar_cambio():
    """Confirmaste: la partida termina como abandono. El cambio se aplica en la
    próxima corrida, después de guardarla (guardar muestra una barra de progreso)."""
    inicializar_estado()  # ver jugar_humano
    pendiente = st.session_state.cambio_pendiente
    st.session_state.cambio_pendiente = None
    if pendiente is None:
        return
    if partida_en_curso():
        st.session_state.abandono = True
    st.session_state.nueva_despues = pendiente


def cancelar_cambio():
    inicializar_estado()  # ver jugar_humano
    st.session_state.cambio_pendiente = None


def texto_confirmacion(pendiente):
    preguntas = {
        "nueva": "¿Empezar una partida nueva?",
        "color": f"¿Jugar con {str(pendiente.get('valor', '')).lower()}?",
        "reloj": f"¿Cambiar el reloj a {pendiente.get('valor')}?",
    }
    return (f"{preguntas[pendiente['tipo']]} Ya hiciste jugadas en esta partida: "
            "se va a guardar como **abandonada** (la perdés).")


# --- Reloj -------------------------------------------------------------------

def tiempos_validos(tiempos):
    """True si tiempos es {blancas: segundos, negras: segundos} con números >= 0."""
    if not isinstance(tiempos, dict):
        return False
    for color in chess.COLORS:
        segundos = tiempos.get(color)
        if not isinstance(segundos, (int, float)) or isinstance(segundos, bool) or segundos < 0:
            return False
    return True


def asegurar_reloj():
    """Deja los tiempos de acuerdo con el reloj elegido. Si están vacíos, rotos
    o son de otro reloj, los reinicia en vez de romper la app.

    Por qué hace falta: los tiempos se crean al empezar una partida, para el
    reloj elegido en ese momento. Si el reloj elegido cambia sin que se
    arranque una partida nueva (por ejemplo, una sesión abierta con una
    versión vieja de la app, o el navegador que se reconecta y le devuelve
    a Streamlit el valor que tenía el selector), los tiempos quedan en None
    con el reloj en 3+2."""
    nombre = st.session_state.get("control", CONTROL_POR_DEFECTO)
    control = CONTROLES.get(nombre)
    if control is None:
        st.session_state.tiempos = None
        st.session_state.reloj_de_los_tiempos = nombre
        return
    if (tiempos_validos(st.session_state.get("tiempos"))
            and st.session_state.get("reloj_de_los_tiempos") == nombre):
        return  # todo en orden
    inicial, _ = control
    st.session_state.tiempos = {chess.WHITE: float(inicial), chess.BLACK: float(inicial)}
    st.session_state.reloj_de_los_tiempos = nombre
    st.session_state.perdio_por_tiempo = None
    st.session_state.inicio_turno = time.time()


def ya_jugo(tablero, color):
    """True si 'color' ya hizo al menos una jugada en la partida.
    Como en Lichess, el reloj de cada uno empieza a correr recién después de
    su primera jugada: la primera jugada de cada bando no gasta tiempo."""
    empieza_color = tablero.root().turn == color  # ¿le tocaba mover primero?
    return len(tablero.move_stack) >= (1 if empieza_color else 2)


def interpretar_jugada(tablero, texto):
    """Convierte el texto del usuario en una jugada.
    Acepta UCI (e2e4, e7e8q) y algebraico (e4, Nf3, O-O).
    Devuelve (jugada, None) si sale bien, o (None, mensaje_de_error)."""
    texto = texto.strip()
    if texto == "":
        return None, "Escribí una jugada."

    # 1) Probamos primero como UCI.
    try:
        jugada = chess.Move.from_uci(texto)
        if jugada in tablero.legal_moves:
            return jugada, None
        return None, f"«{texto}» es ilegal en esta posición."
    except ValueError:
        pass  # no tiene formato UCI: probamos como algebraico

    # 2) Probamos como notación algebraica (SAN).
    #    parse_san ya revisa que la jugada sea legal.
    try:
        return tablero.parse_san(texto), None
    except chess.IllegalMoveError:
        return None, f"«{texto}» es ilegal en esta posición."
    except chess.AmbiguousMoveError:
        return None, (f"«{texto}» es ambigua: hay más de una pieza que puede ir ahí. "
                      "Aclará cuál (por ejemplo Nbd2) o usá UCI.")
    except ValueError:
        return None, (f"No entiendo «{texto}». Usá UCI (e2e4) o algebraico (e4, Nf3). "
                      "Ojo: las piezas van en mayúscula en inglés (N, B, R, Q, K).")


def aplicar_jugada_humana(jugada, tiempo_usado=None):
    """Hace tu jugada, descontando del reloj el tiempo que pensaste.
    tiempo_usado: segundos medidos por el navegador. Si no viene (jugada
    escrita en el cuadro de texto), lo medimos acá con time.time()."""
    tablero = st.session_state.tablero
    yo = color_humano()
    # Tu primera jugada no gasta tiempo (tu reloj todavía no arrancó).
    if hay_reloj() and ya_jugo(tablero, yo):
        asegurar_reloj()
        if tiempo_usado is None:
            tiempo_usado = time.time() - st.session_state.inicio_turno
        _, incremento = control_de_tiempo()
        st.session_state.tiempos[yo] -= max(0.0, tiempo_usado)
        if st.session_state.tiempos[yo] <= 0:
            # La jugada llegó tarde: perdiste por tiempo.
            st.session_state.tiempos[yo] = 0.0
            st.session_state.perdio_por_tiempo = yo
            return
        st.session_state.tiempos[yo] += incremento  # el incremento se suma al jugar
    tablero.push(jugada)
    anotar_reloj(yo)
    st.session_state.mensaje = ""


def jugar_humano():
    """Se ejecuta al apretar Enter en el cuadro de texto. Hace la jugada escrita."""
    # Los callbacks corren ANTES que el resto del archivo: si la sesión viene
    # de una versión vieja, primero completamos las claves que falten.
    inicializar_estado()
    tablero = st.session_state.tablero
    texto = st.session_state.texto_jugada
    st.session_state.texto_jugada = ""  # vaciamos el cuadro de texto

    if partida_terminada(tablero):
        st.session_state.mensaje = "La partida terminó. Empezá una nueva."
        return
    if tablero.turn != color_humano():
        st.session_state.mensaje = "Todavía no es tu turno."
        return

    jugada, error = interpretar_jugada(tablero, texto)
    if error:
        st.session_state.mensaje = error
    else:
        aplicar_jugada_humana(jugada)


def numero_o_none(valor):
    """El número que mandó el JS, o None si no vino o no es un número."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    return None


def jugada_del_tablero():
    """Se ejecuta cuando el componente manda algo (antes de correr el archivo).
    Puede ser una jugada {uci, fen, id, tiempo_usado} o el aviso de que se te
    acabó el tiempo {tiempo_agotado, fen, id}."""
    inicializar_estado()  # ver jugar_humano
    valor = st.session_state[KEY_TABLERO]
    tablero = st.session_state.tablero

    # ¿Se te acabó el tiempo? (Lo detecta el reloj del navegador.)
    if isinstance(valor, dict) and valor.get("tiempo_agotado"):
        if valor.get("id") != st.session_state.ultimo_id_tablero:
            st.session_state.ultimo_id_tablero = valor.get("id")
            # Solo vale si tu reloj ya estaba corriendo (ya hiciste tu primera jugada).
            if (hay_reloj() and not partida_terminada(tablero)
                    and tablero.turn == color_humano() and ya_jugo(tablero, color_humano())):
                asegurar_reloj()
                st.session_state.tiempos[color_humano()] = 0.0
                st.session_state.perdio_por_tiempo = color_humano()
        return

    if partida_terminada(tablero):
        # Por ejemplo, la jugada llegó justo después de quedarte sin tiempo.
        if isinstance(valor, dict) and valor.get("id") is not None:
            st.session_state.ultimo_id_tablero = valor["id"]
        return

    nuevo_id, jugada, error = procesar_valor(
        tablero, valor, st.session_state.ultimo_id_tablero, color_humano())

    # Guardamos el id aunque la jugada se rechace: así no se procesa dos veces
    # y el componente sabe que ya le contestamos.
    st.session_state.ultimo_id_tablero = nuevo_id
    if jugada is not None:
        aplicar_jugada_humana(jugada, numero_o_none(valor.get("tiempo_usado")))
    elif error:
        st.session_state.mensaje = error


def deshacer():
    """Saca jugadas hasta haber sacado una tuya (y la respuesta del bot si la hubo)."""
    inicializar_estado()  # ver jugar_humano
    tablero = st.session_state.tablero
    while tablero.move_stack:
        tablero.pop()
        # Después de pop(), le toca mover a quien hizo la jugada que sacamos.
        # Si ese sos vos, ya deshicimos tu jugada: paramos.
        if tablero.turn == color_humano():
            break
    # Lo anotado de las jugadas que sacamos ya no sirve.
    st.session_state.relojes = st.session_state.relojes[:len(tablero.move_stack)]
    for cantidad in [c for c in st.session_state.evaluaciones if c > len(tablero.move_stack)]:
        del st.session_state.evaluaciones[cantidad]
    st.session_state.revision = None
    st.session_state.evaluaciones_revision = {}
    st.session_state.revisar_pedido = False
    st.session_state.mensaje = ""


def anotar_reloj(color):
    """Después de cada jugada anotamos cuánto tiempo le quedaba al que movió
    (para el [%clk] del PGN). Sin reloj se anota None."""
    relojes = st.session_state.relojes
    # Si faltan datos (por ejemplo, una sesión vieja), completamos con None.
    faltan = len(st.session_state.tablero.move_stack) - 1 - len(relojes)
    relojes.extend([None] * max(0, faltan))
    tiempos = st.session_state.tiempos
    relojes.append(tiempos[color] if hay_reloj() and tiempos else None)


def abandonar():
    inicializar_estado()  # ver jugar_humano
    if not partida_terminada(st.session_state.tablero):
        st.session_state.abandono = True


def nombre_del_nivel():
    """Nivel para el PGN: el que usó MiniMate, o 'mixto' si lo cambiaste en el medio."""
    usados = set(st.session_state.niveles_usados)
    if len(usados) == 1:
        return usados.pop()
    return "mixto" if usados else st.session_state.get("nivel", NIVEL_POR_DEFECTO)


def analizar_partida(tablero, texto):
    """Analiza la partida una sola vez (profundidad 2 con quietud) con una
    barra de progreso. Lo usan el PGN ([%eval]) y la revisión."""
    if st.session_state.analisis_partida is None:
        progreso = st.progress(0.0, text=texto)

        def al_avanzar(hechas, total):
            progreso.progress(hechas / total, text=f"{texto} {hechas}/{total}")

        jugadas_partida = list(tablero.move_stack)
        revision = revisar_partida(jugadas_partida, color_humano(),
                                   inicial=tablero.root(), al_avanzar=al_avanzar)
        # Evaluación de CADA posición (para la barra de la revisión y el PGN),
        # toda del mismo análisis. Casi todas salen de la revisión.
        progreso.progress(1.0, text="Evaluando las posiciones...")
        evaluaciones = evaluaciones_de_la_revision(revision, jugadas_partida,
                                                   inicial=tablero.root())
        progreso.empty()
        st.session_state.analisis_partida = {"revision": revision, "evaluaciones": evaluaciones}
    return st.session_state.analisis_partida


def guardar_si_termino(tablero):
    """Al terminar la partida la guarda (una sola vez). Si no llegaste a hacer
    ninguna jugada, no se guarda (no hay nada tuyo para analizar)."""
    if not partida_terminada(tablero) or st.session_state.partida_guardada:
        return
    st.session_state.partida_guardada = True
    if not ya_jugo(tablero, color_humano()):
        return
    error_sesion = None
    try:
        jugador = jugador_actual()     # None = invitado (sin sesión iniciada)
    except Exception as error:  # noqa: BLE001  (sin conexión con la base: se maneja abajo)
        jugador, error_sesion = None, error
    analisis = analizar_partida(tablero, "Guardando la partida: analizando tus jugadas...")
    if st.session_state.pgn_partida is None:
        st.session_state.pgn_partida = armar_pgn(
            tablero, color_humano(), nombre_del_nivel(),
            st.session_state.get("control", CONTROL_POR_DEFECTO),
            relojes=st.session_state.relojes,
            evaluaciones=analisis["evaluaciones"],
            perdio_por_tiempo=st.session_state.perdio_por_tiempo,
            abandono=st.session_state.abandono,
            jugador=jugador["nombre"] if jugador else None,
            clave_jugador=jugador["clave"] if jugador else None)
    pgn = st.session_state.pgn_partida
    if jugador is None and error_sesion is None:
        # Invitado: no se guarda nada (queda el botón de descarga).
        st.session_state.como_invitado = True
        return
    try:
        if error_sesion is not None:
            raise error_sesion   # no sabemos quién sos porque falló la base
        st.session_state.ruta_guardado = str(guardar_partida(pgn, jugador))
        st.session_state.error_guardado = None
        # Avisamos a la página de estadísticas que hay datos nuevos.
        st.session_state.version_datos = st.session_state.get("version_datos", 0) + 1
    except Exception as error:  # noqa: BLE001
        # Supabase falló (sin internet, clave mal...) o no se pudo escribir el
        # archivo. La partida NO se pierde: queda el botón de descarga y una
        # copia local (si se puede), y se puede reintentar.
        st.session_state.ruta_guardado = None
        st.session_state.error_guardado = resumir_error(error)
        if st.session_state.respaldo_local is None:
            try:
                st.session_state.respaldo_local = str(guardar_en_archivo(pgn))
            except OSError:
                pass


def reintentar_guardado():
    """Botón "Reintentar": vuelve a probar en la próxima corrida."""
    inicializar_estado()  # ver jugar_humano
    st.session_state.partida_guardada = False


def historial_san(tablero):
    """Lista de las jugadas en notación algebraica, ej: ['e4', 'e5', 'Nf3']."""
    # Para escribir cada jugada en SAN hay que conocer la posición de ese momento,
    # así que reproducimos la partida desde la posición inicial (root).
    repaso = tablero.root()
    jugadas = []
    for jugada in tablero.move_stack:
        jugadas.append(repaso.san(jugada))
        repaso.push(jugada)
    return jugadas


def texto_estado(tablero):
    """Devuelve (tipo, texto) describiendo cómo está la partida."""
    if st.session_state.abandono:
        return "error", "Abandonaste. Ganó MiniMate."
    sin_tiempo = st.session_state.perdio_por_tiempo
    if sin_tiempo is not None:
        ganador = not sin_tiempo
        # Regla del ajedrez: si al que le queda tiempo no le alcanza el
        # material para dar mate (por ejemplo, solo el rey), son tablas.
        if tablero.has_insufficient_material(ganador):
            return "info", "Tablas: se acabó el tiempo, pero no había material para dar mate."
        if sin_tiempo == color_humano():
            return "error", "Se te acabó el tiempo. Ganó MiniMate."
        return "success", "¡A MiniMate se le acabó el tiempo! Ganaste. 🎉"

    resultado = tablero.outcome()  # None si la partida sigue
    if resultado is None:
        turno = "Te toca a vos" if tablero.turn == color_humano() else "Le toca a MiniMate"
        if tablero.is_check():
            return "warning", f"¡Jaque! {turno}."
        return "info", f"{turno}."

    if resultado.termination == chess.Termination.CHECKMATE:
        if resultado.winner == color_humano():
            return "success", "¡Jaque mate! Ganaste. 🎉"
        return "error", "Jaque mate. Ganó MiniMate."

    # Todos los demás finales son tablas.
    motivos = {
        chess.Termination.STALEMATE: "ahogado",
        chess.Termination.INSUFFICIENT_MATERIAL: "material insuficiente",
        chess.Termination.SEVENTYFIVE_MOVES: "regla de las 75 jugadas",
        chess.Termination.FIVEFOLD_REPETITION: "quíntuple repetición",
    }
    motivo = motivos.get(resultado.termination, "fin de partida")
    return "info", f"Tablas por {motivo}."


# --- Barra de evaluación ---------------------------------------------------

def valor_de_la_posicion(tablero_mostrado):
    """Evaluación para la barra, sin hacer búsquedas nuevas: usamos el último
    valor que calculó MiniMate (o la revisión) hasta esa jugada."""
    if tablero_mostrado.is_checkmate():
        # Ganó el que acaba de mover (el que NO le toca).
        return VALOR_MATE if tablero_mostrado.turn == chess.BLACK else -VALOR_MATE
    if tablero_mostrado.is_game_over():
        return 0  # tablas
    cantidad = len(tablero_mostrado.move_stack)
    anteriores = [c for c in st.session_state.evaluaciones if c <= cantidad]
    if not anteriores:
        return 0  # todavía no hay evaluación: igualdad
    return st.session_state.evaluaciones[max(anteriores)]


def datos_barra_para(tablero_mostrado):
    if not st.session_state.get("mostrar_barra", True):
        return None
    if en_revision():
        # En la revisión, cada posición tiene su propia evaluación (calculada
        # al revisar): la de la posición que estás viendo, no la del final.
        cantidad = len(tablero_mostrado.move_stack)
        valor = st.session_state.evaluaciones_revision.get(cantidad)
        if valor is not None:
            return datos_barra(valor)
    return datos_barra(valor_de_la_posicion(tablero_mostrado))


# --- Reloj -----------------------------------------------------------------

def datos_reloj(tablero):
    """Lo que necesita el reloj del componente JS (None = no se muestra).
    corre: el color cuyo reloj está corriendo, o None si ninguno (partida
    terminada, o al que le toca todavía no hizo su primera jugada)."""
    if not hay_reloj() or en_revision():
        return None
    asegurar_reloj()  # nunca usar tiempos vacíos o de otro reloj
    corre = None
    if not partida_terminada(tablero) and ya_jugo(tablero, tablero.turn):
        corre = "w" if tablero.turn == chess.WHITE else "b"
    tiempos = st.session_state.tiempos
    return {"w": round(tiempos[chess.WHITE], 2), "b": round(tiempos[chess.BLACK], 2),
            "corre": corre}


# --- Revisión de partida ---------------------------------------------------

def pedir_revision():
    inicializar_estado()  # ver jugar_humano
    st.session_state.revisar_pedido = True


def ir_a_jugada(indice):
    """Muestra en el tablero la posición después de 'indice' jugadas."""
    inicializar_estado()  # ver jugar_humano
    st.session_state.indice_revision = indice


def tablero_en(tablero, indice):
    """Copia del tablero con solo las primeras 'indice' jugadas hechas."""
    copia = tablero.root()
    for jugada in tablero.move_stack[:indice]:
        copia.push(jugada)
    return copia


def analisis_de(indice):
    """El análisis de la jugada número 'indice' (0 = la primera), si es tuya."""
    for analisis in st.session_state.revision:
        if analisis["indice"] == indice:
            return analisis
    return None


def texto_jugada(analisis):
    """Ej: '12. Qf3?? · error grave · mejor Bg4'  o  '12... Nf6 · la mejor'."""
    puntos = "." if color_humano() == chess.WHITE else "..."
    jugada = f"{analisis['numero']}{puntos} {analisis['san']}{SIMBOLOS[analisis['clasificacion']]}"
    if analisis["san"] == analisis["mejor_san"]:
        return f"{jugada} · la mejor"
    if analisis["clasificacion"] is None:
        return f"{jugada} · bien (mejor {analisis['mejor_san']})"
    return f"{jugada} · {analisis['clasificacion']} · mejor {analisis['mejor_san']}"


# ---------------------------------------------------------------------------
# Estado inicial
# ---------------------------------------------------------------------------
# La primera vez crea todo; después solo completa lo que falte (por ejemplo,
# en una sesión que venía de una versión vieja de la app).

inicializar_estado()
tablero = st.session_state.tablero

# ¿Quién juega? Con sesión iniciada (Google o Lichess) las partidas se guardan;
# sin sesión se juega como invitado. (También procesa la vuelta de Lichess.)
jugador = preparar_sesion()

# Un cambio que esperaba confirmación, pero la partida ya terminó (por ejemplo,
# te dieron mate mientras tanto): ya no hace falta preguntar, se aplica.
if st.session_state.cambio_pendiente is not None and not partida_en_curso():
    st.session_state.nueva_despues = st.session_state.cambio_pendiente
    st.session_state.cambio_pendiente = None

# Cambio confirmado: primero se guarda esta partida (como abandono) y después
# se aplica el cambio y empieza la nueva. Va antes de la barra lateral porque
# el valor de un selector solo se puede cambiar antes de dibujarlo.
if st.session_state.nueva_despues is not None:
    pendiente = st.session_state.nueva_despues
    guardar_si_termino(tablero)
    if st.session_state.error_guardado is not None:
        # No se pudo guardar: NO empezamos otra partida, así podés descargar
        # esta o reintentar. El cambio pedido se descarta.
        st.session_state.nueva_despues = None
        st.rerun()
    if pendiente["tipo"] == "color":
        st.session_state.color = pendiente["valor"]
    elif pendiente["tipo"] == "reloj":
        st.session_state.control = pendiente["valor"]
    nueva_partida()
    st.rerun()


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------

# Arriba: tu cuenta (nombre y foto, o los botones para iniciar sesión).
# Durante una partida no se puede entrar ni salir: la página se recarga y la
# partida se perdería.
barra_lateral(bloquear=partida_en_curso())

with st.sidebar:
    st.header("Opciones")
    # Cambiar de color arranca una partida nueva (on_change).
    st.radio("Jugás con", ["Blancas", "Negras"], key="color", on_change=al_cambiar_color)
    # Dificultad: de menos a más Elo. Se puede cambiar en medio de la partida.
    nombre_nivel = st.select_slider("Dificultad de MiniMate", options=list(NIVELES),
                                    value=NIVEL_POR_DEFECTO, key="nivel")
    st.caption(describir(nombre_nivel))
    nivel = NIVELES[nombre_nivel]
    # Reloj: cambiarlo también arranca una partida nueva.
    # (Sin "index": el primero, "Sin reloj", ya es el valor por defecto. Así
    # Streamlit no se queja cuando cambiamos el valor desde session_state.)
    st.selectbox("Reloj (minutos + segundos por jugada)", list(CONTROLES),
                 key="control", on_change=al_cambiar_reloj)
    # Para quien prefiere jugar sin "ayudas".
    st.toggle("Mostrar barra de evaluación", value=True, key="mostrar_barra")
    st.button("Nueva partida", key="nueva_partida", on_click=pedir_nueva_partida,
              width="stretch")
    # Confirmación (si ya hiciste jugadas en la partida actual).
    if st.session_state.cambio_pendiente is not None:
        st.warning(texto_confirmacion(st.session_state.cambio_pendiente))
        si, no = st.columns(2)
        si.button("Sí, abandonar", key="confirmar_cambio", on_click=confirmar_cambio,
                  type="primary", width="stretch")
        no.button("Cancelar", key="cancelar_cambio", on_click=cancelar_cambio,
                  width="stretch")

# Recién acá (después de dibujar el selector) el valor de "control" es seguro:
# si los tiempos no coinciden con el reloj elegido, se reinician.
asegurar_reloj()


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

st.title("♟ MiniMate")
if jugador is None:
    st.info("Estás jugando como **invitado**: tus partidas no se guardan y no tenés "
            "estadísticas. Iniciá sesión (en la barra lateral) para guardarlas.")

columna_tablero, columna_panel = st.columns([3, 2])

with columna_tablero:
    if en_revision():
        # Revisión: la posición elegida, sin poder mover, con una flecha
        # hacia la mejor jugada si la que se jugó fue tuya y no era la mejor.
        indice = st.session_state.indice_revision
        mostrado = tablero_en(tablero, indice)
        flecha = None
        analisis = analisis_de(indice - 1) if indice > 0 else None
        if analisis is not None and analisis["san"] != analisis["mejor_san"]:
            flecha = analisis["mejor_uci"]
        tablero_interactivo(
            mostrado,
            color_humano=color_humano(),
            mi_turno=False,
            id_respondido=st.session_state.ultimo_id_tablero,
            key=KEY_TABLERO,
            on_change=jugada_del_tablero,
            barra=datos_barra_para(mostrado),
            flecha=flecha,
        )
    else:
        tablero_interactivo(
            tablero,
            color_humano=color_humano(),
            mi_turno=es_mi_turno(tablero),
            id_respondido=st.session_state.ultimo_id_tablero,
            key=KEY_TABLERO,
            on_change=jugada_del_tablero,
            barra=datos_barra_para(tablero),
            reloj=datos_reloj(tablero),
        )

with columna_panel:
    # Estado de la partida (jaque, mate, tablas, tiempo...).
    tipo, texto = texto_estado(tablero)
    getattr(st, tipo)(texto)  # llama a st.info / st.warning / st.success / st.error

    if not en_revision():
        # Cuadro para escribir la jugada (alternativa al tablero).
        st.text_input("O escribí tu jugada (e2e4, e4, Nf3...)", key="texto_jugada",
                      on_change=jugar_humano)

        # Mensaje de error de la última jugada, si lo hubo.
        if st.session_state.mensaje:
            st.error(st.session_state.mensaje)

        # Para poder deshacer tiene que existir al menos una jugada tuya.
        # Con negras, la primera jugada siempre es de MiniMate.
        # Con reloj no se puede deshacer (sería hacer trampa con el tiempo).
        minimo = 1 if color_humano() == chess.WHITE else 2
        # Una partida terminada ya quedó guardada: no se puede deshacer.
        st.button("↩ Deshacer mi última jugada", key="deshacer", on_click=deshacer,
                  disabled=(len(tablero.move_stack) < minimo or hay_reloj()
                            or partida_terminada(tablero)),
                  help="Con reloj no se puede deshacer." if hay_reloj() else None)

        if not partida_terminada(tablero):
            # Abandonar: la partida termina (perdida) y se guarda igual.
            st.button("🏳 Abandonar", key="abandonar", on_click=abandonar,
                      disabled=not ya_jugo(tablero, color_humano()),
                      help="Termina la partida como perdida (y la guarda, si "
                           "iniciaste sesión).")

    # Al terminar, se guarda sola (una vez) y se puede descargar y revisar.
    guardar_si_termino(tablero)
    if partida_terminada(tablero):
        if st.session_state.pgn_partida is not None:
            if st.session_state.como_invitado:
                st.warning("Jugaste como invitado: esta partida **no se guardó**. Podés "
                           "descargarla, o iniciar sesión para guardar las próximas.")
            elif st.session_state.ruta_guardado == "Supabase":
                st.caption("💾 Partida guardada en Supabase")
            elif st.session_state.ruta_guardado:
                st.caption(f"💾 Partida guardada en `{st.session_state.ruta_guardado}`")
            if st.session_state.error_guardado is not None:
                aviso = ("**No se pudo guardar la partida en la base de datos** "
                         f"({st.session_state.error_guardado}). No la pierdas: "
                         "descargá el PGN con el botón de abajo, o reintentá.")
                if st.session_state.respaldo_local:
                    aviso += (f" También quedó una copia en `{st.session_state.respaldo_local}` "
                              "(en Streamlit Cloud se borra al reiniciar).")
                st.error(aviso)
                st.button("🔁 Reintentar guardar", key="reintentar_guardado",
                          on_click=reintentar_guardado, width="stretch")
            # En Streamlit Cloud los archivos se borran al reiniciar: descargala.
            st.download_button("⬇ Descargar PGN", data=st.session_state.pgn_partida,
                               file_name=nombre_de_archivo(), mime="application/x-chess-pgn",
                               key="descargar", width="stretch")
        else:
            st.caption("No se guardó: no llegaste a hacer ninguna jugada.")
        if not en_revision() and not st.session_state.revisar_pedido:
            st.button("🔍 Revisar partida", key="revisar", on_click=pedir_revision,
                      type="primary", width="stretch")

    # Análisis de la revisión (una sola vez; después queda guardado).
    # (Si la partida ya se guardó, el análisis está hecho y sale al instante.)
    if st.session_state.revisar_pedido and not en_revision():
        analisis = analizar_partida(tablero, "Analizando tus jugadas...")
        st.session_state.evaluaciones_revision = analisis["evaluaciones"]
        st.session_state.revision = analisis["revision"]
        st.session_state.indice_revision = len(tablero.move_stack)  # empieza en el final
        st.rerun()

    if en_revision():
        st.subheader("Revisión")
        revision = st.session_state.revision
        if not revision:
            st.caption("No hiciste ninguna jugada en esta partida.")
        else:
            cuenta = resumen(revision)
            st.markdown(
                f"**?!** Imprecisiones: **{cuenta['imprecisión']}**  \n"
                f"**?** Errores: **{cuenta['error']}**  \n"
                f"**??** Errores graves: **{cuenta['error grave']}**")

        # Navegación: ◀ y ▶ recorren todas las jugadas (tuyas y del bot).
        indice = st.session_state.indice_revision
        total = len(tablero.move_stack)
        izquierda, centro, derecha = st.columns([1, 2, 1])
        izquierda.button("◀", key="rev_anterior", on_click=ir_a_jugada, args=(indice - 1,),
                         disabled=indice == 0, width="stretch")
        # En número de jugada de ajedrez (no medias jugadas): "13. blancas · 13 de 15".
        # st.caption interpreta Markdown y "13. blancas" sería una lista
        # numerada: con "\." el punto se muestra tal cual.
        centro.caption(texto_contador(tablero.root(), indice, total).replace(".", "\\.", 1))
        derecha.button("▶", key="rev_siguiente", on_click=ir_a_jugada, args=(indice + 1,),
                       disabled=indice == total, width="stretch")

        # Comentario de la jugada que se está viendo, si es tuya.
        analisis = analisis_de(indice - 1) if indice > 0 else None
        if analisis is not None:
            tipos = {"error grave": st.error, "error": st.warning,
                     "imprecisión": st.warning, None: st.success}
            # (Mismo escape que en el contador: si no, "12. Qf3" sería una lista.)
            tipos[analisis["clasificacion"]](texto_jugada(analisis).replace(".", "\\.", 1))

        # Lista de tus jugadas: tocando una, el tablero va a esa posición.
        for analisis in revision:
            elegida = analisis["indice"] + 1 == indice
            st.button(texto_jugada(analisis), key=f"rev_{analisis['indice']}",
                      on_click=ir_a_jugada, args=(analisis["indice"] + 1,),
                      type="primary" if elegida else "secondary", width="stretch")

    # Historial: agrupamos de a dos (blancas, negras) por número de jugada.
    st.subheader("Historial")
    jugadas = historial_san(tablero)
    if not jugadas:
        st.caption("Todavía no hay jugadas.")
    else:
        lineas = []
        for i in range(0, len(jugadas), 2):
            numero = i // 2 + 1
            par = " ".join(jugadas[i:i + 2])
            lineas.append(f"{numero}. {par}")
        st.text("\n".join(lineas))


# ---------------------------------------------------------------------------
# Turno de MiniMate
# ---------------------------------------------------------------------------
# Va al final a propósito: así primero se dibuja el tablero con TU jugada
# y recién después el bot piensa. También cubre el caso de jugar con negras:
# al empezar le toca a MiniMate y juega solo. Al volver a correr el archivo
# (st.rerun) el componente recibe el FEN nuevo y anima la jugada del bot.

if not partida_terminada(tablero) and tablero.turn != color_humano():
    bot = tablero.turn
    profundidad = nivel["profundidad"]
    if hay_reloj():
        # Si le queda poco tiempo, piensa menos (menos profundidad).
        _, incremento = control_de_tiempo()
        profundidad = profundidad_segun_reloj(profundidad, nivel["quietud"],
                                              st.session_state.tiempos[bot], incremento)

    with st.spinner("MiniMate está pensando..."):
        inicio = time.perf_counter()
        # devolver_valor=True: además de la jugada nos da la evaluación,
        # que usamos para la barra sin hacer otra búsqueda.
        jugada, valor = mejor_jugada(tablero, profundidad, con_quietud=nivel["quietud"],
                                     devolver_valor=True)
        pensado = time.perf_counter() - inicio

    # Igual que vos: la primera jugada del bot no gasta tiempo.
    if hay_reloj() and ya_jugo(tablero, bot):
        _, incremento = control_de_tiempo()
        st.session_state.tiempos[bot] -= pensado
        if st.session_state.tiempos[bot] <= 0:
            st.session_state.tiempos[bot] = 0.0
            st.session_state.perdio_por_tiempo = bot  # se le acabó el tiempo al bot
            st.rerun()
        st.session_state.tiempos[bot] += incremento

    tablero.push(jugada)
    anotar_reloj(bot)
    st.session_state.niveles_usados.append(nombre_nivel)
    st.session_state.evaluaciones[len(tablero.move_stack)] = valor
    st.session_state.inicio_turno = time.time()  # empieza tu turno
    st.rerun()
