# ♟ MiniMate

Un bot de ajedrez escrito desde cero en Python, con una app web para jugarle, ver la evaluación y revisar tus errores.

**Jugá contra MiniMate:** [PLACEHOLDER_LINK](PLACEHOLDER_LINK)

## Capturas

| Partida | Revisión | Celular |
|---|---|---|
| ![Partida con reloj y barra de evaluación](docs/img/partida.png) | ![Revisión de partida con la mejor jugada marcada](docs/img/revision.png) | ![MiniMate en el celular](docs/img/celular.png) |

## Qué tiene la app

- **Tablero interactivo**: clic o arrastrar para mover, coronación con menú, funciona con el dedo en el celular.
- **4 niveles de dificultad**, de ≈700 a ≈1650 Elo (ver [Nivel medido](#nivel-medido)).
- **Barra de evaluación** al costado del tablero, como en las páginas de ajedrez, con la ventaja en peones (`+1.5`) o el mate (`M3`). Se puede ocultar.
- **Reloj** opcional: 3+2, 5+3, 10+5 o 15+10. Si al bot le queda poco tiempo, piensa menos.
- **Revisión de partida**: al terminar, MiniMate analiza tus jugadas, marca imprecisiones, errores y errores graves, y te muestra con una flecha qué tendrías que haber jugado.

## Cómo funciona por dentro

### 1. Evaluación: ¿quién va ganando?

Para MiniMate una posición es un número en **centipeones** (100 = un peón). Positivo = mejor para blancas, negativo = mejor para negras.

- **Material**: cada pieza vale un número fijo (peón 100, caballo 320, alfil 330, torre 500, dama 900).
- **Tablas de posición**: un pequeño bonus o castigo según la casilla. Un caballo en el centro vale más que uno en el borde, un peón avanzado vale más que uno en su casilla inicial.
- Mate = ±100000, tablas = 0.

Está en [src/evaluacion.py](src/evaluacion.py) y [src/tablas.py](src/tablas.py).

### 2. Minimax: pensar jugadas hacia adelante

Mirar la posición actual no alcanza: hay que pensar "si yo juego esto, el rival contesta aquello...". **Minimax** prueba todas las jugadas posibles hasta cierta profundidad. Blancas eligen siempre el número más alto y negras el más bajo, suponiendo que el rival juega lo mejor posible.

### 3. Poda alfa-beta: no mirar lo que no hace falta

Si ya encontré una jugada buena, y al revisar otra veo que el rival tiene una respuesta que la deja peor, no hace falta seguir mirando esa otra jugada: ya sé que no la voy a elegir. La **poda alfa-beta** corta esas ramas y llega al mismo resultado que minimax mirando muchas menos posiciones.

### 4. Orden de jugadas (MVV-LVA)

La poda corta más cuanto antes se mira la mejor jugada. Por eso MiniMate ordena las jugadas antes de probarlas: primero las capturas, con el criterio **MVV-LVA** ("víctima más valiosa, atacante menos valioso": comer una dama con un peón va antes que comer un peón con una dama), después las coronaciones y los jaques.

Medido con [prueba_velocidad.py](prueba_velocidad.py) (profundidad 4, con búsqueda de quietud, después de 1. e4 e5 2. Nf3 Nc6):

| Modo | Jugada elegida | Posiciones evaluadas | Segundos |
|---|---|---:|---:|
| Sin ordenar | Bc4 | 42.191 | 5,97 |
| Ordenando (MVV-LVA) | Bc4 | 17.703 | 3,18 |

Misma jugada, **2,4 veces menos posiciones**.

### 5. Búsqueda de quietud

Minimax corta a una profundidad fija, y eso trae un problema: el **efecto horizonte**. Si la última jugada que mira es "mi dama come un peón", ve un peón de más... y no ve que en la jugada siguiente le comen la dama.

La solución: al llegar al final, MiniMate **sigue mirando solo capturas** hasta que la posición esté "quieta". Esta fue la mejora más grande: subió el nivel de ≈1250 a ≈1650 Elo (ver abajo).

### 6. Detección de repeticiones

Si una posición ya apareció antes en la partida, el rival puede repetirla y pedir tablas. Por eso, dentro de la búsqueda, una posición repetida vale 0 (empate): cuando MiniMate va ganando evita repetir, y cuando va perdiendo lo busca.

Todo esto está en [src/motor.py](src/motor.py).

## Nivel medido

Para saber qué tan fuerte es MiniMate lo hice jugar contra [Stockfish](https://stockfishchess.org/), el motor más fuerte que existe, con su fuerza limitada a un Elo fijo (`UCI_LimitStrength`, 0,1 s por jugada). MiniMate jugó a profundidad 3, alternando blancas y negras ([medir_elo.py](medir_elo.py)).

| MiniMate (profundidad 3) | Partidas | vs 1320 | vs 1500 | vs 1700 | Elo estimado |
|---|---:|---|---|---|---:|
| Sin búsqueda de quietud | 10 | 40% (+2 =4 −4) | — | — | **≈ 1250** |
| Con búsqueda de quietud | 30 | 95% (+9 =1 −0) | 75% (+7 =1 −2) | 45% (+3 =3 −4) | **≈ 1670** |
| Con quietud + repeticiones | 60 | 75% (+15 =0 −5) | 75% (+15 =0 −5) | 45% (+7 =4 −9) | **≈ 1615** |

Con la búsqueda de quietud, MiniMate juega en **≈ 1600–1670 Elo**.

Ojo con dos cosas:

- **Es Elo en la escala de Stockfish**, no un Elo oficial de FIDE ni de Lichess o Chess.com: sirve para comparar versiones de MiniMate entre sí.
- **Margen de error**: con 60 partidas es de unos **±90 Elo** (95% de confianza). La diferencia entre 1670 y 1615 está dentro de ese margen: la detección de repeticiones casi no cambió el resultado total, pero bajó las tablas por repetición del 23% al 7%.

Los niveles de la app combinan profundidad y quietud:

| Nivel | Cómo juega | Elo aprox. |
|---|---|---:|
| Principiante | Mira 1 jugada adelante, sin quietud | ≈ 700 |
| Fácil | Mira 2 jugadas adelante, sin quietud | ≈ 1100 |
| Intermedio | Mira 2 jugadas adelante, con quietud | ≈ 1450 |
| Difícil | Mira 3 jugadas adelante, con quietud | ≈ 1650 |

Stockfish no baja de 1320, así que Principiante lo medí haciéndolo jugar contra Fácil ([medir_niveles.py](medir_niveles.py)).

## Estructura del proyecto

```
minimate/
├── app.py                  # la app web (Streamlit)
├── main.py                 # jugar en la terminal
├── src/
│   ├── evaluacion.py       # cuánto vale una posición
│   ├── tablas.py           # tablas de posición de cada pieza
│   ├── motor.py            # minimax, alfa-beta, orden, quietud, repeticiones
│   ├── niveles.py          # niveles de dificultad y su Elo
│   ├── analisis.py         # barra de evaluación y revisión de partida
│   ├── reloj.py            # controles de tiempo y profundidad según el reloj
│   └── componente_tablero/ # tablero interactivo (JavaScript) para Streamlit
├── tests/                  # tests con pytest
├── medir_elo.py            # mide el Elo contra Stockfish
├── medir_niveles.py        # compara niveles de MiniMate entre sí
├── prueba_velocidad.py     # compara con y sin ordenar jugadas
├── motores/                # acá va Stockfish (no se sube al repo)
└── docs/img/               # capturas
```

## Cómo correrlo

Necesitás Python 3.10 o más nuevo.

```bash
git clone <url-del-repo>
cd minimate

# Entorno virtual
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac / Linux

pip install -r requirements.txt

# La app
streamlit run app.py
```

Se abre en el navegador en `http://localhost:8501`. También se puede jugar en la terminal con `python main.py`.

### Tests

```bash
pytest
```

### Medir el Elo

`medir_elo.py` necesita **Stockfish**, que no viene en el repo: hay que descargarlo de [stockfishchess.org/download](https://stockfishchess.org/download/) y poner el ejecutable en la carpeta `motores/`.

```bash
# 10 partidas contra cada nivel de Stockfish (1320, 1500 y 1700)
python medir_elo.py

# Lo mismo que la tabla de arriba: 20 partidas por nivel
python medir_elo.py --profundidad 3 --partidas 20 --niveles 1320 1500 1700

# Sin búsqueda de quietud, para comparar
python medir_elo.py --sin-quietud
```

Las partidas se guardan en un `.pgn` para verlas después en cualquier programa de ajedrez.

## Próximos pasos

- **Profundización iterativa**: buscar a profundidad 1, después 2, después 3... hasta que se acabe el tiempo. Así el bot usaría justo el tiempo que tiene en vez de una profundidad fija, y el orden de cada vuelta ayudaría a la siguiente.
- **Tabla de transposiciones**: guardar las posiciones ya analizadas, porque se llega a la misma posición por distintos caminos. Evitaría repetir trabajo.
- **Evaluación de finales**: hoy el rey vale lo mismo en el centro que en una esquina. En los finales el rey tiene que ir al centro, y hay mates (por ejemplo, rey y torre contra rey) que MiniMate no sabe forzar.
- **Bot de Lichess**: conectar MiniMate a la API de bots de Lichess para que juegue contra gente real y tenga un Elo "de verdad".

## Autor

**Tomás Amaya**, estudiante de Ciencia de Datos en Organizaciones (UNLP).
