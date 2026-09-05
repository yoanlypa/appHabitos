# Desplegar en Railway

Ya está desplegado. Las URLs:

| | |
|---|---|
| Web | https://apphabitos.up.railway.app |
| API | https://apphabitos-production-66a4.up.railway.app |
| Bot | [@apphabitos_bot](https://t.me/apphabitos_bot) |

El repo se llama `appHabitos` y el bot igual: se quedaron del nombre con el
que empezó el proyecto, antes de ser el parte del día.

Dos servicios, los dos desde este mismo repo:

| Servicio | Root Directory | Qué corre |
|---|---|---|
| `backend` | `/backend` | La API **y** el bot, en el mismo proceso |
| `web`     | `/web`     | El front, estático |

## Por qué la API y el bot van juntos

Railway **no deja compartir un volumen entre servicios**, y los dos tienen
que leer y escribir la misma base SQLite. Separarlos le daría a cada uno su
propio disco: lo que anotaras por Telegram no saldría en la web.

Por eso `app/api_y_bot.py` los levanta en un solo proceso. El precio es que
un redespliegue reinicia los dos, y el bot deja de responder unos segundos.

Si algún día molesta, la salida es Postgres: se añade el servicio de base de
datos, se cambia `DATABASE_URL`, y ya se pueden separar. El código no
supone ningún motor concreto.

## 1. Servicio del backend

1. **New Service → GitHub Repo**, y elige este repo.
2. **Settings → Root Directory**: `/backend`
3. **Settings → Config-as-code**: `/backend/railway.json`
   Ojo: la ruta del fichero de configuración **no** sigue al Root Directory,
   hay que escribirla entera desde la raíz del repo.
4. **Settings → Volumes → New Volume**, con el punto de montaje en `/data`.
   Sin volumen, la base se borra en cada despliegue.
5. **Settings → Networking → Generate Domain**, para tener la URL pública.
6. **Variables**:

   ```
   DATABASE_URL=sqlite:////data/parte_del_dia.db
   TELEGRAM_BOT_TOKEN=<el que da @BotFather>
   TZ_LOCAL=Europe/Madrid
   HORA_AVISO=21:00
   CORS_ORIGENES=<la URL del front, se rellena en el paso 3>
   ```

   Las cuatro barras de `sqlite:////data/...` no son una errata: tres son
   ruta relativa, cuatro son ruta absoluta.

## 2. Servicio del front

1. **New Service → GitHub Repo**, el mismo repo.
2. **Settings → Root Directory**: `/web`
3. **Settings → Networking → Generate Domain**.
4. **Variables**: `VITE_API_URL=https://<la URL del backend>` (sin barra final).

No hace falta configurar nada más: Railway detecta que es un proyecto Vite,
ejecuta `npm run build` y sirve `dist/` con Caddy, con el fallback a
`index.html` que necesita una SPA.

## 3. Cerrar el círculo

Cada servicio necesita la URL del otro, así que hay que volver atrás una vez:

1. Copia la URL del front y ponla en `CORS_ORIGENES` del backend.
2. Comprueba que `VITE_API_URL` tiene la URL del backend.
3. Redespliega el front.

**`VITE_API_URL` se hornea al construir**, no se lee en caliente: si algún
día cambias la URL del backend, hay que redesplegar el front, no solo
reiniciarlo.

## Si al entrar la app aparece vacía cada pocos días

Es que la base **no está en el volumen** y se borra con cada despliegue.
Pregúntaselo al propio servicio:

```
curl https://<backend>/salud
```

En `datos.persistente` tiene que poner `true`. Si pone `false`, el campo
`datos.aviso` dice exactamente qué falta. Las tres causas, por frecuencia:

1. **`DATABASE_URL` no está puesta.** El valor por defecto del código es una
   ruta relativa, que cae dentro del contenedor.
2. **Está puesta con tres barras**: `sqlite:///data/...` es *relativa*.
   Tienen que ser cuatro: `sqlite:////data/parte_del_dia.db`.
3. **El volumen no está montado**, o su punto de montaje no es `/data`.

Lo que se hubiera perdido no se recupera; a partir del arreglo, ya no.

## 4. Comprobar que está vivo

```
curl https://<backend>/salud        # {"estado":"ok"}
```

Y en Telegram: `/start`, luego `/web` para sacar un token, y entrar con él
en la web. Si la web da un error de CORS en la consola del navegador, es que
`CORS_ORIGENES` no coincide exactamente con su URL.

## Si la web da 404 nada más generar el dominio

Mira la respuesta: si trae la cabecera `x-railway-fallback: true` y el
cuerpo dice `"Application not found"`, ese 404 **no es de la aplicación**.
Es el edge de Railway diciendo que el dominio no apunta a ningún despliegue
vivo — porque aún está construyendo, o porque el build falló.

Railway te da la URL en cuanto pulsas *Generate Domain*, sin esperar a que
haya nada detrás. Que exista la URL no significa que el servicio esté vivo.

## Si el build del backend falla por la versión de Python

`backend/.python-version` pide 3.14, que es la que se usa en local. Railway
instala la que diga ese fichero; si su builder aún no la tiene, cambia el
contenido a `3.13` y vuelve a desplegar. El código no usa nada específico
de 3.14.
