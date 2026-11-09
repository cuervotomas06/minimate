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
- **Reloj** opcional: 3+2, 5+3, 10+5 o 15+10. Como en Lichess, cada reloj arranca recién después de la primera jugada de ese jugador. Si al bot le queda poco tiempo, piensa menos.
- **Revisión de partida**: al terminar, MiniMate analiza tus jugadas, marca imprecisiones, errores y errores graves, y te muestra con una flecha qué tendrías que haber jugado.
- **Tus partidas como datos**: cada partida se guarda en PGN (con reloj y evaluación por jugada, en el formato de Lichess) y la página **Mis estadísticas** muestra tus patrones: en qué fase perdés, cuántas piezas colgás, tus errores graves recientes.
- **Cuentas**: iniciá sesión con Google o con Lichess (sin sesión se juega como invitado y no se guarda nada). Podés vincular tu cuenta de Lichess y la de Chess.com (verificada con un código en tu perfil) e importar tus partidas desde la app. Cada persona ve solo sus datos. Ver [docs/LOGIN.md](docs/LOGIN.md).

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

Hasta acá es el motor original, en [src/motor.py](src/motor.py). Los niveles Principiante y Fácil todavía juegan con esta búsqueda. Lo que sigue es el motor nuevo, en [src/busqueda.py](src/busqueda.py), que usan Intermedio, Difícil y Experto. Cada mejora se sumó de a una y se midió antes de pasar a la siguiente: v1 tiene solo la 7, v2 suma la 8, y así hasta v5.

### 7. Profundización iterativa (v1)

En vez de buscar a una profundidad fija, MiniMate busca a profundidad 1, después a 2, después a 3... hasta que se acaba el tiempo. Juega la mejor jugada de la **última vuelta completa**. Si una vuelta queda por la mitad, se descarta. Así el bot usa justo el tiempo que tiene: en posiciones simples llega más profundo y en las complicadas no se pasa. Además, cada vuelta empieza por la mejor jugada de la anterior, lo que ayuda mucho a la poda. Tampoco arranca una vuelta nueva si calcula que no le va a alcanzar el tiempo.

### 8. Tabla de transposiciones (v2)

A la misma posición se llega por caminos distintos (1. e4 e5 2. Nf3 y 1. Nf3 e5 2. e4). La **tabla de transposiciones** guarda cada posición ya analizada: a qué profundidad, cuánto valía, si ese valor es exacto o solo un límite (por la poda), y cuál fue la mejor jugada. Si la posición vuelve a aparecer, se reusa ese resultado o, al menos, se prueba primero esa jugada. Tiene un tope de 50.000 posiciones para no llenar la memoria. Los mates se guardan como "mate en N desde acá", para que el valor siga siendo correcto si se llega a esa posición por otro camino.

### 9. Killers e historia (v3)

Más orden de jugadas, ahora para las que no son capturas. Una **jugada killer** es una jugada tranquila que provocó una poda en otra rama a la misma profundidad: es probable que vuelva a servir, así que se prueba pronto. La **historia** lleva la cuenta de qué jugadas tranquilas vienen dando podas en toda la búsqueda.

### 10. Evaluación de finales (v4)

La evaluación ahora cambia de a poco a medida que salen las piezas (**evaluación por fases**):

- **Rey**: en la apertura tiene que esconderse, pero en el final tiene que ir al centro.
- **Peones pasados**: un peón sin peones rivales adelante vale más cuanto más avanzado está, sobre todo en el final.
- **Pareja de alfiles**: tener los dos alfiles suma.
- **Mates básicos**: con mucha ventaja y el rival sin peones, MiniMate empuja al rey rival al borde y acerca el suyo. Antes no sabía dar mate con rey y torre contra rey. Ahora, desde 24 posiciones al azar de rey y dama o rey y torre contra rey, da mate en las 24 (antes, en 9).

El código está en [src/evaluacion_avanzada.py](src/evaluacion_avanzada.py).

### 11. Jugada nula y LMR (v5)

Dos formas de no gastar tiempo en jugadas que seguramente son malas:

- **Jugada nula**: "si yo pasara el turno y aun así el rival no puede hacerme daño, esta posición es tan buena que no vale la pena mirarla a fondo". Se busca con menos profundidad y, si da suficiente, se poda. No se usa en jaque ni en finales con poco material, donde pasar el turno puede ser lo peor (*zugzwang*).
- **LMR** (*late move reductions*): gracias al orden de jugadas, las que aparecen al final de la lista casi nunca son las mejores. Se miran con una jugada menos de profundidad y, solo si sorprenden, se vuelven a mirar completas.

### Calidad de cada jugada, en vivo

Después de cada jugada tuya, la app la califica con los mismos criterios que la revisión: ★ mejor, ✓ buena, ?! imprecisión, ? error, ?? error grave. El símbolo aparece en la casilla de llegada y en el historial. En los errores muestra cuál era la mejor jugada, con una flecha. Ese análisis se descuenta del tiempo que piensa el bot, así que el bot no tarda más. Se puede apagar desde la barra lateral, y la calidad se guarda con la partida (en el PGN, con los símbolos estándar `?!`, `?` y `??`).

## Nivel medido

Para saber qué tan fuerte es MiniMate lo hice jugar contra [Stockfish](https://stockfishchess.org/), el motor más fuerte que existe, con su fuerza limitada a un Elo fijo (`UCI_LimitStrength`, 0,1 s por jugada), alternando blancas y negras ([medir_elo.py](medir_elo.py)). El Elo de todas las partidas juntas se calcula por máxima verosimilitud, con su margen de error al 95%.

### El motor nuevo (v1 a v5)

Cada versión jugó 96 partidas: 32 contra Stockfish 1500, 32 contra 1800 y 32 contra 2100. MiniMate tuvo **1 segundo por jugada**, salvo la referencia "profundidad 3", que no tiene límite de tiempo.

**Condiciones de medición.** Todo se midió en la misma notebook, con un **AMD Ryzen AI 7 350** (8 núcleos, 16 hilos). Como cada versión piensa un tiempo fijo, una compu más lenta busca menos y saca menos Elo. Por eso cada fila dice cuántas partidas se jugaron a la vez y a cuántas posiciones por segundo anduvo MiniMate. En la primera tanda, la notebook se fue calentando y frenando a medida que avanzaba la sesión (de 12.700 a 6.800 posiciones por segundo). Así que esas filas **no son del todo comparables entre sí**: las últimas versiones jugaron con desventaja. La tanda final se midió de nuevo, toda seguida, enchufada y con 4 partidas a la vez para no recalentar.

**Tanda final** (las tres seguidas, en condiciones estables):

| Versión | vs 1500 | vs 1800 | vs 2100 | Elo estimado | Pos/s | A la vez |
|---|---|---|---|---:|---:|---:|
| Referencia: motor original a 1 s | 50% (+13 =6 −13) | 22% (+3 =8 −21) | 11% (+1 =5 −26) | **1560 ± 90** | 6.418* | 4 |
| Referencia: motor original a profundidad 3 | 62% (+19 =2 −11) | 33% (+7 =7 −18) | 34% (+7 =8 −17) | **1730 ± 85** | 6.758* | 4 |
| **v4 a 1 s (versión final)** | 69% (+20 =4 −8) | 34% (+8 =6 −18) | 28% (+5 =8 −19) | **1735 ± 85** | 10.569 | 4 |

**Primera tanda** (una versión por vez, con la notebook frenándose):

| Versión | Qué suma | vs 1500 | vs 1800 | vs 2100 | Elo estimado | Pos/s | A la vez |
|---|---|---|---|---|---:|---:|---:|
| Referencia: original a 1 s | — | 31% | 28% | 14% | 1522 ± 93 | 6.454* | 8 |
| Referencia: original a profundidad 3 | — | 56% | 27% | 33% | 1681 ± 86 | 1.324* | 8 |
| v1 | Profundización iterativa | 61% | 27% | 33% | 1697 ± 86 | 12.703 | 8 |
| v2 | + Tabla de transposiciones | 50% | 36% | 23% | 1659 ± 86 | 12.680 | 8 |
| v3 | + Killers e historia | 62% | 41% | 17% | 1697 ± 86 | 10.980 | 8 |
| v4 | + Evaluación de finales | 73% | 36% | 14% | 1708 ± 85 | 9.989 | 8 |
| v5 | + Jugada nula y LMR | 58% | 30% | 19% | 1647 ± 87 | 6.834 | 8 |

\* El motor original cuenta solo las posiciones que **evalúa**, no todas las que visita, así que su número no se compara directamente con el de v1 a v5. Sí muestra cuánto se frenó la notebook: la referencia a profundidad 3 tardó 38 minutos en la primera tanda y 15 en la final.

**Enfrentamiento directo v4 contra v5** ([comparar_versiones.py](comparar_versiones.py)): 96 partidas, 1 s por jugada, 48 aperturas jugadas con los dos colores, 4 a la vez, enchufada. v4 sacó 50,5 de 96 (53%): **v4 − v5 = +18 ± 63 Elo**, a unas 11.850 posiciones por segundo cada una. Esta prueba es la más justa entre dos versiones, porque juegan en la misma compu al mismo tiempo. Si la compu se frena, las afecta a las dos por igual.

**Qué aprendí de cada mejora.** Las diferencias entre versiones son más chicas que el margen de error (±85 con 96 partidas), así que además del Elo medí un **diagnóstico**: las mismas 30 posiciones de partidas reales, contando cuántas posiciones hace falta revisar y a qué profundidad llega en 1 segundo.

| Versión | Posiciones a prof. 4 | Prof. promedio en 1 s | Llega a 4 en 1 s |
|---|---:|---:|---:|
| v1 | 646.406 | 3,30 | 10/30 |
| v2 | 399.054 (−38%) | 3,57 | 16/30 |
| v3 | 326.725 (−18%) | 3,80 | 23/30 |
| v4 | 354.941 (+9%) | — | — |
| v5 | 239.774 (−32%) | — | — |

(Las profundidades de v4 y v5 se midieron con la notebook frenada, así que no van en la tabla. Los conteos de posiciones no dependen de la velocidad.)

- **v2 y v3** hacen lo que tienen que hacer: con la misma profundidad revisan bastante menos posiciones, así que llegan más profundo en el mismo tiempo.
- **v4** revisa un poco más (la evaluación cambia el orden de las jugadas), pero aprendió a ganar los finales: desde 24 posiciones de rey y dama o rey y torre contra rey, da mate en las 24 y en la mitad de jugadas, contra 9 de 24 de v3.
- **v5 no quedó.** Revisa un 32% menos de posiciones, pero eso no se tradujo en mejores resultados. Perdió por poco el enfrentamiento directo con v4 y salió más baja contra Stockfish. A esta profundidad (3 o 4 jugadas), recortar ramas cuesta más de lo que ahorra. El criterio fue: **una mejora queda solo si en partidas muestra algo a favor, aunque sea dentro del margen; si no, gana la versión más simple.** El código sigue en [src/busqueda.py](src/busqueda.py), apagado, por si con más velocidad vale la pena.

**En resumen**: el motor nuevo a 1 s juega igual que el original a profundidad 3 (1735 contra 1730). La diferencia es que siempre respeta el tiempo, lo que hace falta para jugar con reloj, y sabe ganar los finales. Contra el original con el mismo segundo por jugada, saca unos **175 Elo** más.

### Historia: el motor original

MiniMate jugó a profundidad 3.

| MiniMate (profundidad 3) | Partidas | vs 1320 | vs 1500 | vs 1700 | Elo estimado |
|---|---:|---|---|---|---:|
| Sin búsqueda de quietud | 10 | 40% (+2 =4 −4) | — | — | **≈ 1250** |
| Con búsqueda de quietud | 30 | 95% (+9 =1 −0) | 75% (+7 =1 −2) | 45% (+3 =3 −4) | **≈ 1670** |
| Con quietud + repeticiones | 60 | 75% (+15 =0 −5) | 75% (+15 =0 −5) | 45% (+7 =4 −9) | **≈ 1615** |

Con la búsqueda de quietud, MiniMate juega en **≈ 1600–1670 Elo**.

Ojo con dos cosas:

- **Es Elo en la escala de Stockfish**, no un Elo oficial de FIDE ni de Lichess o Chess.com: sirve para comparar versiones de MiniMate entre sí.
- **Margen de error**: con 60 partidas es de unos **±90 Elo** (95% de confianza). La diferencia entre 1670 y 1615 está dentro de ese margen: la detección de repeticiones casi no cambió el resultado total, pero bajó las tablas por repetición del 23% al 7%.

### Niveles de la app

| Nivel | Cómo juega | Elo aprox. |
|---|---|---:|
| Principiante | Motor original: mira 1 jugada adelante, sin quietud | ≈ 700 |
| Fácil | Motor original: mira 2 jugadas adelante, sin quietud | ≈ 1100 |
| Intermedio | Motor nuevo (v4), piensa hasta 0,3 s por jugada | ≈ 1580 (± 81) |
| Difícil | Motor nuevo (v4), piensa hasta 1 s por jugada | ≈ 1740 (± 85) |
| Experto | Motor nuevo (v4), piensa hasta 3 s por jugada | ≈ 1900 (± 85) |

Principiante y Fácil son a propósito débiles y no cambiaron (hay un test que comprueba que juegan exactamente igual que antes), así que su Elo sigue valiendo. Stockfish no baja de 1320, así que Principiante lo medí haciéndolo jugar contra Fácil ([medir_niveles.py](medir_niveles.py)). Intermedio, Difícil y Experto se midieron con 96 partidas cada uno, en la misma notebook, enchufada, 4 a la vez, a unas 10.600, 10.600 y 11.300 posiciones por segundo. Intermedio jugó contra Stockfish 1320, 1500 y 1800, y los otros dos contra 1500, 1800 y 2100.

**Ojo:** los niveles por tiempo dependen del procesador. En Streamlit Cloud, que es más lento que esta notebook, llegan menos profundo y juegan algo más débil que lo que dice la tabla. Con reloj, el bot nunca piensa más que lo que le corresponde según el tiempo que le queda ([src/reloj.py](src/reloj.py)), así que no pierde por tiempo.

## Estructura del proyecto

```
minimate/
├── app.py                  # la app web (Streamlit): arma el menú de páginas
├── paginas/
│   ├── jugar.py            # página Jugar: el tablero contra MiniMate
│   └── estadisticas.py     # página Mis estadísticas
├── main.py                 # jugar en la terminal
├── src/
│   ├── evaluacion.py       # cuánto vale una posición
│   ├── tablas.py           # tablas de posición de cada pieza
│   ├── motor.py            # minimax, alfa-beta, orden, quietud, repeticiones
│   ├── busqueda.py         # motor nuevo: iterativa, transposiciones, killers, nula, LMR
│   ├── evaluacion_avanzada.py  # evaluación por fases, finales, peones pasados
│   ├── niveles.py          # niveles de dificultad y su Elo
│   ├── analisis.py         # barra de evaluación y revisión de partida
│   ├── reloj.py            # controles de tiempo y profundidad según el reloj
│   ├── guardado.py         # PGN de cada partida y dónde se guarda (Supabase o archivo)
│   ├── base_de_datos.py    # conexión con Supabase (leer y escribir filas)
│   ├── jugador.py          # normalizar y comparar nombres
│   ├── cuentas.py          # quién inició sesión y sus cuentas vinculadas
│   ├── panel_cuenta.py     # la parte visual: iniciar sesión, vincular, importar
│   ├── lichess.py          # Lichess: login OAuth2 con PKCE y export de partidas
│   ├── chesscom.py         # Chess.com: API pública y verificación con código
│   ├── importar.py         # importar partidas de cuentas vinculadas
│   ├── datos.py            # partidas -> DataFrames (pandas) para analizarlas
│   └── componente_tablero/ # tablero interactivo (JavaScript) para Streamlit
├── importar_chesscom.py    # baja tus partidas de Chess.com (API pública)
├── subir_a_supabase.py     # sube a Supabase las partidas que tenías en datos/
├── migrar_jugador.py       # pasa las partidas de un jugador viejo a tu cuenta
├── supabase/               # SQL de las tablas, migraciones y cómo configurar Supabase
├── docs/LOGIN.md           # cómo configurar el login con Google y Lichess
├── datos/                  # partidas y caché locales, si no usás Supabase (no se sube)
├── tests/                  # tests con pytest
├── medir_elo.py            # mide el Elo contra Stockfish
├── medir_niveles.py        # compara niveles de MiniMate entre sí
├── comparar_versiones.py   # enfrenta dos versiones del motor (v1..v5)
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

# Como la tanda final de arriba: v4 con 1 s por jugada, 4 partidas a la vez,
# cortando si MiniMate baja de 6.000 posiciones por segundo
python medir_elo.py --version v4 --tiempo-minimate 1 --partidas 32 --niveles 1500 1800 2100 --paralelo 4 --velocidad-minima 6000

# Enfrentamiento directo entre dos versiones (96 partidas)
python comparar_versiones.py v4 v5 --aperturas 48 --tiempo 1 --paralelo 4
```

Las partidas se guardan en un `.pgn` para verlas después en cualquier programa de ajedrez.

## Próximos pasos

- **Velocidad**: MiniMate está escrito en Python puro y revisa unas 10.000 posiciones por segundo; los motores en C llegan a millones. Generar las jugadas más rápido es lo que más profundidad daría.
- **Bot de Lichess**: conectar MiniMate a la API de bots de Lichess para que juegue contra gente real y tenga un Elo "de verdad".

## Autor

**Tomás Amaya**, estudiante de Ciencia de Datos en Organizaciones (UNLP).
