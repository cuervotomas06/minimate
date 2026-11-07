# Página "Mis estadísticas": cómo jugás, a partir de tus partidas guardadas.
#
# Aparece en el menú lateral gracias a app.py (st.navigation).
# Los datos salen de src/datos.py (partidas de MiniMate, Chess.com y Lichess),
# de Supabase si hay credenciales o de los archivos de datos/ si no. Siempre
# solo las del jugador con la sesión iniciada: sin sesión, no hay estadísticas.

import chess
import chess.svg
import pandas as pd
import streamlit as st

from src import base_de_datos
from src.datos import FASES, cargar_todo, carpeta_datos, fase_de_la_derrota
from src.panel_cuenta import barra_lateral, botones_de_inicio, preparar_sesion, seccion_cuentas
from src.motor import mejor_jugada

st.set_page_config(page_title="Mis estadísticas · MiniMate", page_icon="📊")

# Un solo color para los gráficos de una sola serie (azul del tema).
COLOR_SERIE = "#2a78d6"


# ttl=300: como mucho cada 5 minutos se vuelve a leer (por ejemplo, si
# importaste partidas de Chess.com desde la terminal).
@st.cache_data(show_spinner="Leyendo tus partidas...", ttl=300)
def cargar(clave_jugador, jugador_id, firma):
    """Lee las partidas del jugador (y solo las suyas). 'firma' hace que la
    caché se renueve cuando hay datos nuevos (ver firma_de)."""
    return cargar_todo(jugador=clave_jugador, jugador_id=jugador_id)


def firma_de(carpeta):
    """Algo que cambia cuando hay partidas nuevas: con archivos, sus fechas de
    modificación; con Supabase, un contador que sube cada vez que la página
    Jugar guarda una partida."""
    if base_de_datos.hay_supabase():
        return ("supabase", st.session_state.get("version_datos", 0))
    if not carpeta.exists():
        return ()
    archivos = sorted(carpeta.glob("*.pgn")) + sorted(carpeta.glob("*.parquet"))
    return (str(carpeta),) + tuple((a.name, a.stat().st_mtime) for a in archivos)


def porcentaje(parte, total):
    return f"{100 * parte / total:.0f}%" if total else "—"


jugador = preparar_sesion()
barra_lateral()
st.title("📊 Mis estadísticas")

# Las estadísticas son tuyas: sin sesión iniciada no hay nada que mostrar.
if jugador is None:
    st.info("**Iniciá sesión para ver tus estadísticas.** Como invitado podés jugar, "
            "pero las partidas no se guardan.")
    botones_de_inicio("estadisticas")
    st.stop()

# Cuentas de Chess.com y Lichess: vincularlas e importar partidas.
with st.expander("🔗 Mis cuentas de ajedrez e importar partidas"):
    seccion_cuentas(jugador)

try:
    partidas, jugadas = cargar(jugador["clave"], jugador["id"], firma_de(carpeta_datos()))
except base_de_datos.ErrorBaseDeDatos as error:
    st.error(f"No se pudieron leer tus partidas de la base de datos ({error}). "
             "Revisá la conexión y volvé a cargar la página.")
    st.stop()

if partidas.empty:
    donde = ("en la base de datos" if base_de_datos.hay_supabase()
             else "en `datos/partidas.pgn`")
    st.info(
        "Todavía no hay partidas para analizar.\n\n"
        "**Cómo empezar:**\n"
        "1. Jugá contra MiniMate en la página **Jugar**. Cada partida que "
        f"termina (o abandonás) se guarda sola {donde}.\n"
        "2. Opcional: vinculá tu cuenta de Chess.com o Lichess e importá tus "
        "partidas (arriba, en «Mis cuentas de ajedrez»).")
    if not base_de_datos.hay_supabase():
        st.caption("Sin base de datos, en Streamlit Cloud los archivos se borran al "
                   "reiniciar la app: conviene correr MiniMate en tu compu.")
    st.stop()

# Filtro por origen (MiniMate / Chess.com), arriba de todo.
origenes = sorted(partidas["origen"].unique())
nombres = {"minimate": "MiniMate", "chesscom": "Chess.com", "lichess": "Lichess"}
elegidos = st.multiselect("Partidas de", origenes, default=origenes,
                          format_func=lambda o: nombres.get(o, o))
partidas = partidas[partidas["origen"].isin(elegidos)]
jugadas = jugadas[jugadas["partida"].isin(partidas["partida"])]
if partidas.empty:
    st.warning("Elegí al menos un origen.")
    st.stop()

mias = jugadas[jugadas["es_mia"]]

# --- Números principales ------------------------------------------------------
total = len(partidas)
blancas = partidas[partidas["color"] == "blancas"]
negras = partidas[partidas["color"] == "negras"]
colgadas_por_partida = mias.groupby("partida")["pieza_colgada"].sum().reindex(
    partidas["partida"], fill_value=0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Partidas jugadas", total)
col2.metric("Victorias con blancas", porcentaje((blancas["resultado"] == "victoria").sum(), len(blancas)),
            help=f"{len(blancas)} partidas con blancas")
col3.metric("Victorias con negras", porcentaje((negras["resultado"] == "victoria").sum(), len(negras)),
            help=f"{len(negras)} partidas con negras")
col4.metric("Piezas colgadas", f"{colgadas_por_partida.mean():.1f}",
            help="Promedio por partida de jugadas tuyas que dejaron una pieza (no peón) "
                 "para que el rival la coma gratis o con una pieza de menos valor.")

# Aviso si hay jugadas sin evaluar (partidas de Chess.com sin --evaluar).
sin_evaluar = mias["perdida"].isna().mean() if len(mias) else 0
if sin_evaluar > 0.05:
    st.caption(f"⚠ El {sin_evaluar:.0%} de tus jugadas todavía no tiene evaluación, así que los "
               "errores y las fases están incompletos. Tocá «Actualizar» en «Mis cuentas "
               "de ajedrez» para que MiniMate las analice.")

# --- ¿En qué fase pierdo? -------------------------------------------------------
st.subheader("¿En qué fase pierdo la partida?")
st.caption("En cada partida perdida, la fase de tu peor jugada (la que más empeoró la evaluación).")
por_fase = fase_de_la_derrota(partidas, jugadas)
if por_fase.sum() == 0:
    st.caption("Todavía no hay derrotas con evaluación.")
else:
    tabla_fases = pd.DataFrame({"Fase": FASES, "Derrotas": por_fase.reindex(FASES).values})
    st.bar_chart(tabla_fases, x="Fase", y="Derrotas", color=COLOR_SERIE, horizontal=True,
                 sort=False, height=200)

# --- Piezas colgadas en el tiempo ------------------------------------------------
st.subheader("Piezas colgadas por partida")
orden = partidas.sort_values("fecha")[["partida", "fecha"]].reset_index(drop=True)
serie = orden.assign(colgadas=colgadas_por_partida.reindex(orden["partida"]).values)
serie["Partida"] = range(1, len(serie) + 1)
# Promedio móvil de 5 partidas: muestra la tendencia sin tanto "ruido".
serie["Promedio (últimas 5)"] = serie["colgadas"].rolling(5, min_periods=1).mean()
st.line_chart(serie, x="Partida", y="Promedio (últimas 5)", color=COLOR_SERIE, height=220)

# --- Errores graves recientes ---------------------------------------------------
st.subheader("Tus 5 errores graves más recientes")
graves = mias[mias["clasificacion"] == "error grave"].sort_values(
    ["fecha", "indice"], ascending=False).head(5)
if graves.empty:
    st.caption("No hay errores graves (o todavía no hay evaluaciones). ¡Bien!")
for _, fila in graves.iterrows():
    tablero = chess.Board(fila["fen_antes"])
    jugada = chess.Move.from_uci(fila["uci"])
    mejor = mejor_jugada(tablero, 2)  # una búsqueda corta, solo para la flecha verde
    flechas = [chess.svg.Arrow(jugada.from_square, jugada.to_square, color="#e34948cc")]
    if mejor is not None and mejor != jugada:
        flechas.append(chess.svg.Arrow(mejor.from_square, mejor.to_square, color="#15781bcc"))
    mi_color = chess.WHITE if fila["color"] == "blancas" else chess.BLACK
    svg = chess.svg.board(tablero, arrows=flechas, orientation=mi_color, size=280,
                          lastmove=tablero.peek() if tablero.move_stack else None)

    izquierda, derecha = st.columns([1, 1])
    izquierda.image(svg, width=280)
    puntos = "." if fila["color"] == "blancas" else "..."
    fecha = fila["fecha"].strftime("%d/%m/%Y") if pd.notna(fila["fecha"]) else "sin fecha"
    derecha.markdown(
        f"**{fila['numero']}{puntos} {fila['san']}??**  \n"
        f"Perdiste **{fila['perdida'] / 100:.1f}** peones "
        f"({fila['eval_antes'] / 100:+.1f} → {fila['eval_despues'] / 100:+.1f}).  \n"
        f"Mejor: **{tablero.san(mejor) if mejor else '—'}** (flecha verde).  \n"
        f"Fase: {fila['fase']} · {nombres.get(fila['origen'], fila['origen'])} · {fecha}")
