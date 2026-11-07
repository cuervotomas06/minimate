# Punto de entrada de MiniMate. Se abre con: streamlit run app.py
#
# Este archivo solo arma el menú de páginas (st.navigation) y abre la elegida.
# Cada página es un archivo de la carpeta paginas/:
#   - Jugar (paginas/jugar.py): el tablero contra MiniMate.
#   - Mis estadísticas (paginas/estadisticas.py): tus patrones de juego.
# Con st.navigation podemos elegir el nombre que aparece en el menú lateral
# (con la carpeta pages/ Streamlit usaría el nombre del archivo: "app").

import streamlit as st

pagina = st.navigation([
    st.Page("paginas/jugar.py", title="Jugar", icon="♟", default=True),
    st.Page("paginas/estadisticas.py", title="Mis estadísticas", icon="📊"),
])
pagina.run()
