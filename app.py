# Interfaz web de MiniMate con Streamlit.
# Se abre con: streamlit run app.py
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

from src.analisis import SIMBOLOS, datos_barra, resumen, revisar_partida
from src.componente_tablero import procesar_valor, tablero_interactivo
from src.evaluacion import VALOR_MATE
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
    """Devuelve chess.WHITE o chess.BLACK según lo elegido en la barra lateral."""
    return chess.WHITE if st.session_state.color == "Blancas" else chess.BLACK


def control_de_tiempo():
    """(segundos iniciales, incremento) del reloj elegido, o None sin reloj."""
    return CONTROLES[st.session_state.get("control", CONTROL_POR_DEFECTO)]


def hay_reloj():
    return control_de_tiempo() is not None


def en_revision():
    """True mientras estás revisando la partida (el tablero no deja mover)."""
    return st.session_state.revision is not None


def partida_terminada(tablero):
    """Terminó por las reglas (mate, tablas...) o porque alguien se quedó sin tiempo."""
    return tablero.is_game_over() or st.session_state.perdio_por_tiempo is not None


def es_mi_turno(tablero):
    return (not partida_terminada(tablero) and not en_revision()
            and tablero.turn == color_humano())


def nueva_partida():
    """Arranca una partida desde cero."""
    st.session_state.tablero = chess.Board()
    st.session_state.mensaje = ""
    # Evaluación de MiniMate después de cada jugada suya:
    # {cantidad de jugadas hechas: valor}. Sirve para la barra.
    st.session_state.evaluaciones = {}
    # Reloj: segundos que le quedan a cada uno (None = sin reloj).
    control = control_de_tiempo()
    if control is None:
        st.session_state.tiempos = None
    else:
        inicial, _ = control
        st.session_state.tiempos = {chess.WHITE: float(inicial), chess.BLACK: float(inicial)}
    st.session_state.inicio_turno = time.time()  # cuándo empezó tu turno
    st.session_state.perdio_por_tiempo = None     # color que se quedó sin tiempo
    # Revisión de partida.
    st.session_state.revision = None         # lista de análisis (None = no estás revisando)
    st.session_state.revisar_pedido = False  # apretaste "Revisar partida"
    st.session_state.indice_revision = 0     # cuántas jugadas se ven en el tablero


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
    if hay_reloj():
        if tiempo_usado is None:
            tiempo_usado = time.time() - st.session_state.inicio_turno
        _, incremento = control_de_tiempo()
        yo = color_humano()
        st.session_state.tiempos[yo] -= max(0.0, tiempo_usado)
        if st.session_state.tiempos[yo] <= 0:
            # La jugada llegó tarde: perdiste por tiempo.
            st.session_state.tiempos[yo] = 0.0
            st.session_state.perdio_por_tiempo = yo
            return
        st.session_state.tiempos[yo] += incremento  # el incremento se suma al jugar
    tablero.push(jugada)
    st.session_state.mensaje = ""


def jugar_humano():
    """Se ejecuta al apretar Enter en el cuadro de texto. Hace la jugada escrita."""
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
    valor = st.session_state[KEY_TABLERO]
    tablero = st.session_state.tablero

    # ¿Se te acabó el tiempo? (Lo detecta el reloj del navegador.)
    if isinstance(valor, dict) and valor.get("tiempo_agotado"):
        if valor.get("id") != st.session_state.ultimo_id_tablero:
            st.session_state.ultimo_id_tablero = valor.get("id")
            if hay_reloj() and not partida_terminada(tablero) and tablero.turn == color_humano():
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
    tablero = st.session_state.tablero
    while tablero.move_stack:
        tablero.pop()
        # Después de pop(), le toca mover a quien hizo la jugada que sacamos.
        # Si ese sos vos, ya deshicimos tu jugada: paramos.
        if tablero.turn == color_humano():
            break
    # Las evaluaciones de las jugadas que sacamos ya no sirven.
    for cantidad in [c for c in st.session_state.evaluaciones if c > len(tablero.move_stack)]:
        del st.session_state.evaluaciones[cantidad]
    st.session_state.revision = None
    st.session_state.revisar_pedido = False
    st.session_state.mensaje = ""


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
    return datos_barra(valor_de_la_posicion(tablero_mostrado))


# --- Reloj -----------------------------------------------------------------

def datos_reloj(tablero):
    """Lo que necesita el reloj del componente JS (None = no se muestra)."""
    if not hay_reloj() or en_revision():
        return None
    corre = None  # partida terminada: ningún reloj corre
    if not partida_terminada(tablero):
        corre = "w" if tablero.turn == chess.WHITE else "b"
    tiempos = st.session_state.tiempos
    return {"w": round(tiempos[chess.WHITE], 2), "b": round(tiempos[chess.BLACK], 2),
            "corre": corre}


# --- Revisión de partida ---------------------------------------------------

def pedir_revision():
    st.session_state.revisar_pedido = True


def ir_a_jugada(indice):
    """Muestra en el tablero la posición después de 'indice' jugadas."""
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
# Estado inicial (solo la primera vez que se abre la página)
# ---------------------------------------------------------------------------

if "color" not in st.session_state:
    st.session_state.color = "Blancas"
# ("revision" es de las claves nuevas: si falta, la sesión venía de una
# versión vieja de la app y arrancamos de cero.)
if "tablero" not in st.session_state or "revision" not in st.session_state:
    nueva_partida()
if "ultimo_id_tablero" not in st.session_state:
    st.session_state.ultimo_id_tablero = None  # id de la última jugada del componente

tablero = st.session_state.tablero


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Opciones")
    # Cambiar de color arranca una partida nueva (on_change).
    st.radio("Jugás con", ["Blancas", "Negras"], key="color", on_change=nueva_partida)
    # Dificultad: de menos a más Elo. Se puede cambiar en medio de la partida.
    nombre_nivel = st.select_slider("Dificultad de MiniMate", options=list(NIVELES),
                                    value=NIVEL_POR_DEFECTO, key="nivel")
    st.caption(describir(nombre_nivel))
    nivel = NIVELES[nombre_nivel]
    # Reloj: cambiarlo también arranca una partida nueva.
    st.selectbox("Reloj (minutos + segundos por jugada)", list(CONTROLES),
                 index=list(CONTROLES).index(CONTROL_POR_DEFECTO),
                 key="control", on_change=nueva_partida)
    # Para quien prefiere jugar sin "ayudas".
    st.toggle("Mostrar barra de evaluación", value=True, key="mostrar_barra")
    st.button("Nueva partida", on_click=nueva_partida, width="stretch")


# ---------------------------------------------------------------------------
# Pantalla principal
# ---------------------------------------------------------------------------

st.title("♟ MiniMate")

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
        st.button("↩ Deshacer mi última jugada", key="deshacer", on_click=deshacer,
                  disabled=len(tablero.move_stack) < minimo or hay_reloj(),
                  help="Con reloj no se puede deshacer." if hay_reloj() else None)

        # Al terminar la partida se puede revisar.
        if partida_terminada(tablero) and not st.session_state.revisar_pedido:
            st.button("🔍 Revisar partida", key="revisar", on_click=pedir_revision,
                      type="primary", width="stretch")

    # Análisis de la revisión (una sola vez; después queda guardado).
    if st.session_state.revisar_pedido and not en_revision():
        progreso = st.progress(0.0, text="Analizando tus jugadas...")

        def al_avanzar(hechas, total):
            progreso.progress(hechas / total, text=f"Analizando tus jugadas... {hechas}/{total}")

        revision = revisar_partida(list(tablero.move_stack), color_humano(),
                                   inicial=tablero.root(), al_avanzar=al_avanzar)
        # La evaluación después de cada jugada tuya también sirve para la barra.
        for analisis in revision:
            st.session_state.evaluaciones[analisis["indice"] + 1] = analisis["valor"]
        st.session_state.revision = revision
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
        centro.caption(f"Jugada {indice} de {total}")
        derecha.button("▶", key="rev_siguiente", on_click=ir_a_jugada, args=(indice + 1,),
                       disabled=indice == total, width="stretch")

        # Comentario de la jugada que se está viendo, si es tuya.
        analisis = analisis_de(indice - 1) if indice > 0 else None
        if analisis is not None:
            tipos = {"error grave": st.error, "error": st.warning,
                     "imprecisión": st.warning, None: st.success}
            tipos[analisis["clasificacion"]](texto_jugada(analisis))

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

    if hay_reloj():
        _, incremento = control_de_tiempo()
        st.session_state.tiempos[bot] -= pensado
        if st.session_state.tiempos[bot] <= 0:
            st.session_state.tiempos[bot] = 0.0
            st.session_state.perdio_por_tiempo = bot  # se le acabó el tiempo al bot
            st.rerun()
        st.session_state.tiempos[bot] += incremento

    tablero.push(jugada)
    st.session_state.evaluaciones[len(tablero.move_stack)] = valor
    st.session_state.inicio_turno = time.time()  # empieza tu turno
    st.rerun()
