# Nombre del jugador: para que las partidas de cada persona queden separadas.
#
# Ojo: es una separación, no una contraseña. Cualquiera que escriba el mismo
# nombre ve y suma partidas a esa persona (la app no tiene usuarios con login).

LARGO_MAXIMO = 40


def normalizar_nombre(texto):
    """Saca espacios de más: '  Tomás   Amaya ' -> 'Tomás Amaya'."""
    return " ".join(str(texto or "").split())[:LARGO_MAXIMO]


def clave_del_nombre(texto):
    """Versión para comparar: sin importar mayúsculas ni espacios de más.
    'Tomás' y ' tomás ' son el mismo jugador."""
    return normalizar_nombre(texto).casefold()


def pedir_nombre():
    """Formulario "¿Cómo te llamás?". Cuando lo completás, guarda el nombre en
    la sesión (st.session_state.jugador) y vuelve a correr la página."""
    import streamlit as st

    st.markdown("Para guardar tus partidas y ver tus estadísticas, decinos cómo te llamás.")
    with st.form("formulario_nombre"):
        nombre = st.text_input("¿Cómo te llamás?", max_chars=LARGO_MAXIMO,
                               placeholder="Tu nombre o apodo", key="nombre_escrito")
        enviado = st.form_submit_button("Empezar", type="primary")
    st.caption("Es solo para separar las partidas de cada persona: no es una contraseña.")
    if enviado:
        limpio = normalizar_nombre(nombre)
        if not limpio:
            st.error("Escribí un nombre.")
        else:
            st.session_state.jugador = limpio
            st.rerun()
