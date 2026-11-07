# Iniciar sesión en MiniMate

MiniMate tiene dos formas de iniciar sesión:

- **Google** (con `st.login` de Streamlit). Hay que crear credenciales en Google Cloud: es lo que explica esta guía.
- **Lichess** (OAuth2 con PKCE). No hay que registrar nada en Lichess.

Sin sesión se puede jugar como **invitado**: no se guarda nada y no hay estadísticas.

Todos los secretos van en `.streamlit/secrets.toml` (que está en el `.gitignore`) y, en Streamlit Cloud, en **Settings → Secrets**. Nunca en el repositorio.

---

## 1. Credenciales de Google (Google Cloud Console)

### 1.1 Crear un proyecto

1. Entrá a <https://console.cloud.google.com/> con tu cuenta de Google.
2. Arriba, en el selector de proyectos → **Proyecto nuevo** → nombre: `MiniMate` → **Crear**.
3. Fijate que quede seleccionado el proyecto nuevo.

### 1.2 Pantalla de consentimiento

Es lo que ve la gente cuando toca "Iniciar sesión con Google".

1. Menú ☰ → **APIs y servicios** → **Pantalla de consentimiento de OAuth** (en la versión nueva se llama **Google Auth Platform**). Tocá **Comenzar**.
2. **Información de la app:** nombre `MiniMate`, y tu email como email de asistencia.
3. **Público:** **Externo** (cualquier cuenta de Google, no solo de una organización).
4. **Información de contacto:** tu email. Aceptá la política y tocá **Crear**.
5. **Acceso a los datos** (*Data access*): MiniMate solo usa `openid`, `email` y `profile`, que son los que pide `st.login` por defecto. Son permisos "no sensibles", así que no hace falta agregar nada.

### 1.3 Usuarios de prueba

Mientras la app está en modo **Prueba** (*Testing*), solo pueden entrar las cuentas que agregues como usuarios de prueba.

1. **Público** (*Audience*) → **Usuarios de prueba** → **Agregar usuarios**.
2. Agregá tu Gmail (y el de quien quieras que pruebe).

Para que entre cualquiera: **Público** → **Publicar app**. Con solo `openid`, `email` y `profile`, Google normalmente no pide verificación.

### 1.4 Crear el cliente OAuth

1. **Clientes** (o **Credenciales** → **Crear credenciales** → **ID de cliente de OAuth**).
2. Tipo de aplicación: **Aplicación web**. Nombre: `MiniMate`.
3. En **URIs de redireccionamiento autorizados** agregá las dos:
   - Local: `http://localhost:8501/oauth2callback`
   - Streamlit Cloud: `https://TU-APP.streamlit.app/oauth2callback` (con el nombre de tu app)

   `/oauth2callback` es la dirección que Streamlit usa para recibir la respuesta de Google. Tiene que coincidir **exacta**, letra por letra.
4. **Crear**. Copiá el **ID de cliente** y el **Secreto del cliente**. El secreto no se puede volver a ver después; si lo perdés, se crea otro.

---

## 2. `secrets.toml`

### En tu compu (`.streamlit/secrets.toml`)

```toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "PEGÁ-ACÁ-UNA-CADENA-LARGA-AL-AZAR"
client_id = "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxxxxxxxxxxxxxxxxxxxxxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[supabase]
url = "https://abcdefghijklmnop.supabase.co"
clave = "sb_secret_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

# Opcional: pasar tus partidas viejas (jugador "mantarraya") a tu cuenta de
# Google la primera vez que entres. Ver la sección 5.
[migracion]
jugador_anterior = "mantarraya"
email = "tu.email@gmail.com"
```

Qué es cada valor de `[auth]`:

| Clave | Qué es |
|---|---|
| `redirect_uri` | A dónde vuelve Google después de iniciar sesión. Tiene que estar en la lista del paso 1.4. |
| `cookie_secret` | Clave con la que Streamlit firma la cookie que dice "esta persona inició sesión". Si alguien la consigue, podría hacerse pasar por cualquiera. Generala al azar con `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `client_id` / `client_secret` | Los del paso 1.4. El secreto es secreto (solo vive en el servidor). |
| `server_metadata_url` | Dónde está la configuración de Google para OpenID Connect. Siempre es la misma. |

### En Streamlit Cloud (Settings → Secrets)

Es el mismo texto con tres diferencias:

```toml
[auth]
redirect_uri = "https://TU-APP.streamlit.app/oauth2callback"
cookie_secret = "OTRA-CADENA-AL-AZAR-DISTINTA-DE-LA-LOCAL"
client_id = "...el mismo..."
client_secret = "...el mismo..."
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[lichess]
redirect_uri = "https://TU-APP.streamlit.app/"
```

| | Local | Streamlit Cloud |
|---|---|---|
| `[auth] redirect_uri` | `http://localhost:8501/oauth2callback` | `https://TU-APP.streamlit.app/oauth2callback` |
| `cookie_secret` | uno | otro distinto (así, si se filtra uno, el otro sigue seguro) |
| `[lichess] redirect_uri` | opcional (se deduce: `http://localhost:8501/`) | **obligatorio**: `https://TU-APP.streamlit.app/` |

¿Por qué en Cloud hay que escribir la dirección de Lichess a mano? En tu compu la app la deduce de la dirección de la página. En un servidor eso no es seguro: esa dirección sale de un dato del pedido (el encabezado `Host`) que un atacante puede falsificar, para que Lichess le mande el código de inicio de sesión a su propio sitio. Si falta, la app no muestra el botón de Lichess.

---

## 3. Lichess

No hay que registrar nada. La app pide **cero permisos**: solo lee tu id y tu usuario, y después revoca el acceso, así que no guarda ningún token.

- **Iniciar sesión con Lichess** (barra lateral): para entrar sin Google.
- **Vincular Lichess** (Mis estadísticas → Mis cuentas de ajedrez): para sumarlo a tu cuenta de Google y poder importar tus partidas de Lichess.

El botón abre Lichess en otra pestaña. Al autorizar, quedás en MiniMate en esa pestaña nueva.

Con Lichess, la sesión dura mientras no recargues la página. Con Google queda guardada en una cookie, así que sobrevive a una recarga.

---

## 4. Chess.com

Chess.com no ofrece "Iniciar sesión con Chess.com" sin aprobación, así que se verifica con un código:

1. **Mis estadísticas → Mis cuentas de ajedrez** → escribí tu usuario → **Generar código** (por ejemplo `MINIMATE-7K3Q`).
2. En chess.com: **Configuración → Perfil** → ponelo en **Ubicación** y guardá.
3. **Verificar**. Si Chess.com tarda en mostrar el cambio, probá de nuevo en un minuto.

El código vence a los 15 minutos. Después de verificar, podés borrarlo del perfil.

---

## 5. Pasar tus partidas viejas ("mantarraya") a tu cuenta

Hay dos formas:

- **Automática:** con la sección `[migracion]` del `secrets.toml` de arriba. La primera vez que entres con Google, si tu email coincide y Google confirma que es tuyo, tus partidas pasan a tu cuenta. El email se usa solo para esta mudanza, que configurás vos. Para todo lo demás la cuenta se identifica por el `sub` de Google.
- **A mano:**
  ```bash
  python migrar_jugador.py --listar
  python migrar_jugador.py --desde mantarraya --hacia google:TU_SUB
  ```
  Tu clave (`google:...`) aparece en **Mis estadísticas → Mis cuentas de ajedrez**.

---

## 6. Probar en tu compu

```bash
pip install -r requirements.txt
streamlit run app.py
```

Abrí `http://localhost:8501` y tocá **Iniciar sesión con Google**. Si Google dice `redirect_uri_mismatch`, la dirección del paso 1.4 no coincide exacta con la de `secrets.toml`.
