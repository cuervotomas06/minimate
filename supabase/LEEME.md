# MiniMate + Supabase

Con Supabase, las partidas se guardan en una base de datos Postgres en la nube
en vez de en `datos/partidas.pgn`. Así no se pierden cuando Streamlit Cloud
reinicia la app, y cada jugador ve solo sus partidas.

Si no configurás nada, MiniMate sigue guardando en archivos locales como antes.

## 1. Crear las tablas

Abrí el proyecto en Supabase → **SQL Editor** → pegá todo
[`esquema.sql`](esquema.sql) → **Run**. Se puede volver a correr sin romper nada.

Qué hace cada parte:

| Parte | Qué crea | Para qué |
|---|---|---|
| 1 | `jugadores` | Una fila por persona. `clave` es el nombre en minúscula y sin espacios de más, y es única: "Tomás" y " tomás " son el mismo jugador. |
| 2 | `partidas` | Una fila por partida, con las mismas columnas que la tabla `partidas` de `src/datos.py` (incluida `origen`: `minimate` o `chesscom`), más `jugador_id`, el PGN completo y una `clave` para no repetir. `unique (jugador_id, clave)` impide guardar la misma partida dos veces. |
| 3 | `jugadas` | Una fila por jugada, con las columnas de la tabla `jugadas` de `src/datos.py`. `origen` y `fecha` no se repiten acá: se toman de la partida. Si se borra una partida, se borran sus jugadas (`on delete cascade`). |
| 4 | `evaluaciones` | La caché de evaluaciones de MiniMate (posición → valor). Es compartida entre jugadores, porque una posición vale lo mismo para todos. |
| 5 | función `guardar_partida` | Guarda una partida y sus jugadas en una sola transacción: o se guarda todo o nada. Si la partida ya estaba, no hace nada. |
| 6 | `grant` / `revoke` | Permisos. Como el proyecto tiene desactivado *"Automatically expose new tables"*, las tablas nuevas no son accesibles por la API hasta que se les da permiso. Solo se lo damos a `service_role` (la clave secreta), y se lo sacamos explícitamente a `anon` y `authenticated` (las claves públicas). |
| 7 | RLS y políticas | Row Level Security queda activado en las cuatro tablas. Hay una política de acceso total para `service_role`. Para `anon` y `authenticated` no hay ninguna: con RLS activado y sin políticas, no ven ni escriben nada. |

### Migración 01: cuentas (Google, Lichess, Chess.com)

Después de `esquema.sql`, corré **una vez** [`migracion_01_cuentas.sql`](migracion_01_cuentas.sql).
Solo agrega cosas; no toca los datos que ya hay.

| Parte | Qué hace |
|---|---|
| 1 | Tabla `cuentas`: une un jugador con una cuenta externa (`proveedor` = `google`, `lichess` o `chesscom`; `id_externo`, `usuario`, `verificado`, `vinculada`). `unique (proveedor, id_externo)`: cada cuenta externa, un solo jugador. |
| 2 | Permite `origen = 'lichess'` en `partidas`. |
| 3 | Función `fusionar_jugadores`: pasa partidas y cuentas de un jugador a otro sin duplicar, en una transacción. Se usa para mudar "mantarraya" a tu cuenta, y cuando alguien entró primero con Lichess y después lo vincula a Google. |
| 4 y 5 | Igual que el resto: `GRANT` solo a `service_role`, RLS activado, ninguna política para `anon` ni `authenticated`. |

## 2. Qué clave usar

En Supabase → **Project Settings** → **API Keys** hay dos tipos de clave:

- **Publishable** (`sb_publishable_...`, antes "anon"): está pensada para ir en
  el navegador, a la vista de cualquiera. La seguridad depende de que el RLS
  filtre por usuario logueado (`auth.uid()`).
- **Secret** (`sb_secret_...`, antes "service_role"): saltea el RLS y puede
  hacer todo. **Nunca** tiene que llegar al navegador ni a GitHub.

**MiniMate usa la clave secreta.** Las razones:

1. **Corre en el servidor.** Todo el código de Streamlit (incluido el que habla
   con Supabase) corre en el servidor. El navegador solo recibe la página, así
   que la clave nunca sale de ahí.
2. **El login no es de Supabase.** Entrás con Google (`st.login`) o con
   Lichess, y quien verifica la sesión es el servidor de Streamlit, no
   Supabase. Por eso el RLS no puede filtrar por "usuario logueado"
   (`auth.uid()` estaría vacío). Con la clave pública habría que dejar que
   `anon` lea y escriba todo, y como esa clave es pública, cualquiera podría
   usarla desde afuera de la app. Con la clave secreta, `anon` no tiene ningún
   permiso, y la única puerta de entrada es la app, que filtra todo por el
   jugador de la sesión.
3. **Dónde vive la clave:** solo en `.streamlit/secrets.toml` (que está en el
   `.gitignore`) o en los *Secrets* de Streamlit Cloud.

El login (Google o Lichess) está explicado en [`docs/LOGIN.md`](../docs/LOGIN.md).
Sin sesión iniciada se juega como invitado y no se escribe nada en la base.

## 3. Configurar las credenciales

Creá `.streamlit/secrets.toml` (ya está en el `.gitignore`, no se sube a GitHub):

```toml
[supabase]
url = "https://abcdefghijklmnop.supabase.co"
clave = "sb_secret_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

- `url`: Project Settings → Data API → *Project URL*.
- `clave`: Project Settings → API Keys → la clave **secreta**.

En **Streamlit Cloud**: la app → Settings → **Secrets** → pegá ese mismo texto.

Los scripts (`importar_chesscom.py`, `subir_a_supabase.py`) leen el mismo
archivo si los corrés desde la carpeta del proyecto. También aceptan las
variables de entorno `SUPABASE_URL` y `SUPABASE_CLAVE`.

## 4. Subir lo que ya tenías

```bash
python subir_a_supabase.py --jugador "mantarraya"
```

- **Qué sube:** `datos/partidas.pgn`, `datos/chesscom.pgn` y la caché `datos/evaluaciones.parquet`.
- **De quién quedan:** cada partida va al jugador que dice su encabezado `Jugador`. Las viejas, que no lo tienen, van a `--jugador`.
- **Sin duplicar:** se puede correr varias veces y no duplica nada.

Esto deja las partidas a nombre del jugador viejo "mantarraya". Para pasarlas a
tu cuenta de Google, ver la sección 5 de [`docs/LOGIN.md`](../docs/LOGIN.md).

## 5. Si Supabase falla

Si al terminar una partida no hay conexión o Supabase da un error, la app:

- avisa con un mensaje rojo;
- deja el botón **Descargar PGN**;
- guarda una copia en `datos/partidas.pgn` (que después podés subir con el script de arriba);
- ofrece **Reintentar**.
