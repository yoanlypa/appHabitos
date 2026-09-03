# Parte del día

Control diario de trabajos, ingresos y gastos. Empezó como un bot de
Telegram y una web, y se está reescribiendo como un backend único (API +
bot) que ambos adaptadores comparten, más un front en React más adelante.

Dueño: Yoa (GitHub: `yoanlypa`). Español siempre, en el código y al hablar
conmigo — comentarios, nombres de variables donde tenga sentido, mensajes
de commit.

## Por qué esta arquitectura

Antes había dos copias de la misma lógica: una en el bot de Telegram, otra
en la web en React. Cambiar cómo se calcula un balance significaba tocarlo
dos veces, en dos idiomas, y eso es exactamente donde este tipo de
proyectos se rompe.

La solución: un único backend en Python. La API HTTP y el bot de Telegram
son dos puertas de entrada distintas a la misma lógica de negocio. Ninguno
de los dos tiene reglas propias — solo llaman a `servicios/`.

## Regla de dependencias (no negociable)

Las capas se importan en una sola dirección:

```
api/   \
bot/    >---> servicios/ ---> dominio/ ---> nucleo/
```

- `nucleo/` no sabe que existe un negocio. Solo configuración y conexión a
  datos.
- `dominio/` no sabe que existe HTTP ni Telegram. Modelos de base de datos
  y reglas puras (interpretar texto, calcular totales). Se puede probar
  sin arrancar ningún servidor.
- `servicios/` son los casos de uso (crear un apunte, cerrar el día,
  marcar cobrado). Es la única capa que toca la base de datos a través de
  `dominio/`.
- `api/` y `bot/` son adaptadores finos. Si tienen lógica de negocio
  propia, está mal colocada — debería vivir en `servicios/`.

Nunca al revés: `dominio/` no importa nada de `servicios/`, `servicios/`
no importa nada de `api/` ni `bot/`.

## Estructura de carpetas

```
parte-del-dia/
├── CLAUDE.md              este archivo
├── backend/
│   ├── app/
│   │   ├── nucleo/        ✅ hecho — config.py, db.py, tiempo.py
│   │   ├── dominio/       ✅ hecho — models.py (Apunte, Ajuste, TokenAcceso, Centimos), parsing.py
│   │   ├── servicios/     ✅ hecho — apuntes.py, resumen.py, export.py, auth.py
│   │   ├── api/           ✅ hecho — main.py, dependencias.py, schemas.py, apuntes.py, resumen.py, export.py
│   │   └── bot/           ✅ hecho — main.py, handlers.py, formato.py, avisos.py
│   ├── requirements.txt
│   ├── Procfile           ✅ dos procesos: web (uvicorn) y bot (polling)
│   └── .env.example
└── web/                   ⬜ Vite + React + TypeScript, más adelante
```

## Decisiones ya tomadas

- **Dinero en céntimos, como enteros.** Nunca float para importes. Un
  0,1 + 0,2 en coma flotante da 0,30000000000000004, y en una cuenta de
  ingresos eso acaba en un descuadre de céntimos que nadie sabe de dónde
  sale. `dominio/models.py` debe convertir a céntimos al guardar y a euros
  al leer.
- **Base de datos**: SQLite en local y en Railway (volumen montado en
  `/data`), con posibilidad de pasar a Postgres solo cambiando
  `DATABASE_URL` — el código no debe suponer un motor concreto.
- **SQLite en modo WAL.** La API y el bot van a leer y escribir la misma
  base de datos a la vez; sin WAL se bloquean entre ellos.
- **Zona horaria**: `Europe/Madrid`, configurable por variable de entorno
  (`TZ_LOCAL`), nunca hardcodeada fuera de `nucleo/config.py`.
- **Despliegue**: Railway, dos servicios desde el mismo repo
  (`backend/` con root directory propio; `web/` más adelante). Variables
  de entorno documentadas en `backend/.env.example`.
- **Sin contraseñas.** El acceso a la web usa un token (`TokenAcceso`,
  `servicios/auth.py`) contra el header `Authorization: Bearer`, no
  usuario/contraseña. Falta que el bot lo genere con `/web`
  (`servicios.auth.generar_token()` ya está listo para que ese handler lo
  llame); hasta entonces se genera a mano.

## Convenciones de código

- Español en identificadores donde aporte claridad de negocio (`crear_apunte`,
  `del_mes`, `pendiente`), inglés en lo puramente técnico si es más
  idiomático en la librería que se esté usando.
- Docstring corto al principio de cada archivo explicando su porqué, no
  solo su qué.
- Nada de lógica de negocio en `api/` ni `bot/`: si un handler hace más
  que parsear la entrada, llamar a un servicio y formatear la salida, algo
  está mal colocado.
- Cada pieza nueva se prueba con un script rápido antes de darla por
  cerrada (crear datos de prueba, comprobar el cálculo, comprobar el caso
  límite). No hace falta un framework de tests todavía, pero sí evidencia
  de que funciona antes de pasar a la siguiente capa.

## Estado actual

`nucleo/`, `dominio/`, `servicios/` y `api/` están escritos y probados (no
se vuelven a tocar salvo que aparezca una necesidad concreta):

- `nucleo/config.py`, `nucleo/db.py`, `nucleo/tiempo.py` — leen variables
  de entorno, normalizan la URL de Postgres, crean tablas, abren y cierran
  sesiones, y dan la hora/fecha local (`hoy_local()`) según `TZ_LOCAL`. En
  Windows hace falta el paquete `tzdata` para que `zoneinfo` conozca
  `Europe/Madrid` (ya está en `requirements.txt`, marcado solo para
  `sys_platform == "win32"`).
- `dominio/models.py` — tabla `Apunte` (id, user_id, fecha, tipo
  trabajo/gasto, concepto, importe, pendiente, origen web/bot, creado),
  `Ajuste` (preferencias de aviso) y `TokenAcceso` (user_id, token único).
  El tipo `Centimos` (TypeDecorator) hace la conversión: euros como
  `Decimal` en Python, céntimos como `Integer` en la BD — verificado que
  120€ se guarda como 12000.
- `dominio/parsing.py` — `interpretar_texto()` reconoce los tres formatos
  (trabajo cobrado, `pendiente ...`, gasto con `-`), probado con decimales
  con coma y con texto sin importe (levanta `TextoNoInterpretable`).
- `servicios/apuntes.py` — `crear_apunte()` / `marcar_cobrado()`.
  `servicios/resumen.py` — `resumen_dia()` / `resumen_mes()` devuelven
  `ResumenPeriodo` (cobrado, pendiente, gastos, `neto`). `servicios/export.py`
  — `exportar_csv()`. `servicios/auth.py` — `generar_token()` /
  `usuario_por_token()`, listo para que el futuro handler `/web` del bot
  llame a `generar_token()`.
- `api/main.py` monta tres routers sobre FastAPI: `POST /apuntes`,
  `POST /apuntes/{id}/cobrado`, `GET /resumen/dia`, `GET /resumen/mes`,
  `GET /export/csv`, `GET /salud`. Todas menos `/salud` exigen
  `Authorization: Bearer <token>` (`api/dependencias.py`, 401 si falta o
  no es válido). Probado levantando el servidor real con uvicorn y
  `curl`: crear los tres tipos de apunte, 401 sin token, 422 con texto
  sin importe, marcar cobrado (+404 si no existe), resumen antes/después
  de cobrar, y export a CSV — todo correcto de punta a punta por HTTP.
- `bot/main.py` arranca por **polling** (no webhook: no necesita URL
  pública, y en Railway es otro proceso del mismo repo — ver `Procfile`).
  `bot/handlers.py` tiene `/start`, `/hoy`, `/mes`, `/cobrado <id>`,
  `/web`, y un handler de texto libre que anota cualquier mensaje que no
  sea comando. `bot/formato.py` solo pinta (importes a la española:
  `1.234,50 €`). Probado con un `Update` simulado, sin tocar Telegram:
  los tres tipos de apunte, texto no entendido, `/cobrado` con y sin
  almohadilla, sin argumento y con id inexistente, resumen antes/después
  de cobrar, y `/web` generando un token que `usuario_por_token()` acepta.
  **Sin probar contra Telegram real: hace falta un `TELEGRAM_BOT_TOKEN`.**
- Se eliminaron `app/config.py`, `db.py`, `models.py`, `schemas.py`,
  `crud.py`, `auth.py` y `app/routers/`: eran los stubs vacíos del scaffold
  original, ya sustituidos 1:1 por los de arriba. También `bot/parsing.py`,
  que habría duplicado `dominio/parsing.py` — el bot pasa el texto tal cual
  al servicio.
- `user_id` es `BigInteger` en las tres tablas: los ids de Telegram ya
  superan el INT de 32 bits de Postgres. En SQLite daba igual, pero el
  motor puede cambiar.
- `nucleo/db.py` expone dos formas de sesión: `get_db()` (dependencia de
  FastAPI) y `sesion()` (context manager, para el bot y los scripts).

- El aviso diario (`bot/avisos.py` + `servicios/avisos.py`) manda el
  resumen del día a la hora de `HORA_AVISO` (21:00 por defecto). Dos
  decisiones de negocio, que por eso viven en el servicio y no en el bot:
  se avisa solo a quien haya anotado algo ese día (un recordatorio vacío
  cada noche es la mejor forma de que silencien el bot), y los avisos
  están activos salvo que los apagues con `/avisos off` — así `Ajuste`
  solo guarda fila para quien ha cambiado algo. Probado con tres usuarios
  (uno los apaga, otro no anota nada, otro sí) y comprobando que si uno
  bloqueó el bot los demás reciben su aviso igual.

**Siguiente paso: el front en `web/`.** Hace falta añadir CORS a la API
antes de que el front pueda llamarla. La pantalla de entrada usa el token
que da `/web` en el bot.

Pendiente menor: el `.gitignore` de la raíz tiene pegado dentro el
heredoc con el que se creó (`cat > .gitignore <<'EOF'` … `EOF`). Las
líneas de patrón funcionan, las dos sobrantes son inertes.