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
│   │   ├── nucleo/        ✅ config.py, db.py, tiempo.py, migraciones.py,
│   │   │                     transcripcion.py
│   │   ├── dominio/       ✅ models.py (Apunte, Cliente, Cita, Ajuste, TokenAcceso, Centimos),
│   │   │                     parsing.py, parsing_citas.py, habitos.py, copia_csv.py
│   │   ├── servicios/     ✅ apuntes, resumen, export, auth, avisos, clientes,
│   │   │                     agenda, trimestres, voz, notas, restauracion, habitos
│   │   ├── api/           ✅ dependencias, schemas, apuntes, resumen, export,
│   │   │                     clientes, agenda, notas, habitos
│   │   └── bot/           ✅ main.py, handlers.py, formato.py, avisos.py,
│   │                         copias.py, alarma.py, restaurar.py, habitos.py
│   ├── requirements.txt
│   ├── Procfile           ✅ dos procesos: web (uvicorn) y bot (polling)
│   └── .env.example
└── web/                   ✅ hecho — api.ts + componentes/{Entrada,Panel}.tsx
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
- **Despliegue**: Railway, dos servicios desde el mismo repo (`backend/` y
  `web/`, cada uno con su root directory). Pasos en `DESPLIEGUE.md`,
  variables en `backend/.env.example`.
- **La API y el bot corren en el mismo proceso en producción**
  (`app/api_y_bot.py`). No es una preferencia: Railway no deja compartir un
  volumen entre servicios, y separarlos le daría a cada uno su propia base
  SQLite — lo anotado por Telegram no saldría en la web. El precio, asumido,
  es que un redespliegue reinicia los dos. La salida, si molesta algún día,
  es pasar a Postgres y separarlos: solo cambia `DATABASE_URL`.
  En local se siguen arrancando por separado.
- **El esquema se cambia con Alembic, nunca con `create_all()`.**
  `create_all` crea las tablas que faltan pero no toca las que ya existen:
  añadir una columna no llegaba nunca a producción. `nucleo/migraciones.py`
  aplica las migraciones al arrancar y sabe marcar las bases anteriores a
  Alembic (stamp del esquema inicial y luego upgrade). Dos detalles que
  costaron sangre: la `naming_convention` de `nucleo/db.py` es obligatoria
  porque SQLite recrea la tabla entera para alterarla y necesita nombrar
  las restricciones, y `render_item` en `alembic/env.py` escribe `Centimos`
  como `sa.Integer` para que las migraciones no importen la aplicación.
- **La base tiene que estar en el volumen, y eso se comprueba, no se
  supone.** Pasó dos veces: los datos se perdían en cada `git push` porque
  en Railway faltaba `DATABASE_URL` y la app usaba la ruta por defecto,
  dentro del contenedor. La app arrancaba igual, sólo que vacía.
  `nucleo/almacenamiento.py` lo detecta y `/salud` lo dice
  (`"persistente": false`), pero eso solo sirve si alguien lo mira: tras
  tocar variables o volúmenes en Railway, abrir `/salud` es obligatorio.
  Y como nadie mira un log, ahora lo dice donde se mira:
  - **El bot avisa por Telegram** (`bot/alarma.py`): al arrancar, a los ids
    de `ALARMA_TELEGRAM_IDS`, y en el primer mensaje de cada persona tras
    cada arranque, sin configurar nada. No se pueden sacar los destinatarios
    de la base, porque justo cuando falla está recién creada y vacía. Una
    vez por persona y no en cada mensaje: un aviso repetido se deja de leer.
  - **La web pone una franja roja** que no se puede cerrar, entrada
    incluida. Si `/salud` no contesta no la pone: una alarma falsa enseña a
    ignorar las verdaderas.
  - **La copia se puede restaurar**: se le reenvía al bot el CSV del domingo
    (`dominio/copia_csv.py`, `servicios/restauracion.py`, `bot/restaurar.py`).
    Un apunte "ya está" si coinciden fecha, tipo, concepto e importe;
    `pendiente` no cuenta, o un trabajo cobrado después volvería a ser
    deuda. Se cuenta en vez de comparar uno a uno, porque dos gasolinas de
    45 el mismo día son dos. Siempre enseña antes lo que va a meter y pide
    un sí: una copia vieja devolvería lo que se borró adrede después. La
    copia no lleva clientes ni citas, así que eso no vuelve.

- **`func.sum()` sobre un importe ya devuelve euros.** El tipo `Centimos`
  se aplica también a los agregados, así que dividir otra vez entre 100 es
  un error de escala de cien veces. Pasó y lo cazó una prueba que comparaba
  el total de la lista con el de la ficha.
- **El cliente se reconoce solo, pero nunca se adivina.** Al anotar, se
  busca en el texto el nombre de un cliente ya dado de alta: si hay uno
  solo, el apunte queda colgado de él sin preguntar; si hay dos Anas, se
  pregunta (botones en el bot, botones en la web). Un trabajo colgado de la
  Ana equivocada es peor que un trabajo sin cliente, y sale caro porque se
  descubre semanas después al ir a cobrar. Nombre y apellido gana al nombre
  de pila, así que decir "Ana Ruiz" evita la pregunta.
  No se inventan clientes: si el nombre no está de alta no se crea nada,
  porque no hay forma de saber si "cocina" es una persona. Alta con
  `/cliente` en el bot o desde la web.
- **Los importes salen siempre con dos decimales.** Pydantic serializa
  `Decimal("120")` como `"120"` y `Decimal("45.5")` como `"45.5"`; en el CSV
  que va al gestor, una columna con esa mezcla parece mal apuntada. El tipo
  `Importe` de `api/schemas.py` lo normaliza.
- **Copia de seguridad por Telegram** (`bot/copias.py`): el histórico
  entero en CSV, cada domingo y con `/copia` cuando se quiera. El sitio más
  seguro para estos datos no es el servidor — ya se perdieron una vez por
  tenerlos sólo ahí. El CSV va en utf-8 **con BOM** para que Excel no
  convierta "Reforma baño" en "Reforma baÃ±o".
- **El trimestre cuenta lo cobrado, no lo facturado**, y la estimación del
  modelo 130 (20% del neto) se presenta siempre como orientativa: aquí no
  se sabe qué gastos son deducibles ni qué retenciones han practicado los
  clientes. Nunca sustituye a una gestoría.
- **Las notas de voz se transcriben y se anotan solas.** Se apunta con las
  manos ocupadas, que es justo cuando se pierden los trabajos: mandar un
  audio al bot tiene que valer lo mismo que escribirlo. Transcribe OpenAI
  (`nucleo/transcripcion.py`, `OPENAI_API_KEY`, menos de un céntimo por
  minuto); el OGG/Opus de Telegram va tal cual, sin convertir nada ni
  necesitar ffmpeg. Tres decisiones que no son de adorno:
  - **Es asíncrono.** La API y el bot comparten proceso, así que transcribir
    en bloqueante dejaría la web colgada varios segundos por cada nota.
  - **Se responde siempre con lo que se ha entendido.** Si oyó "120" donde
    se dijo "20", hay que verlo en el momento y no al cuadrar el mes.
  - **Nada de lo anotado se pierde por no llevar importe** (`admite_nota` en
    `servicios/apuntes`). "Llamar a Ana el martes" se guarda como apunte de
    tipo `nota` (importe 0, no suma en ningún resumen) en lugar de
    rechazarse.
  Sin clave el bot lo dice y no pasa nada más: el audio sigue en el chat.

- **Escribir es gratis y también se guarda todo.** El audio se manda cuando
  no hay más remedio (con las manos ocupadas), y solo entonces se paga por
  transcribirlo; teclear no llama a nadie de fuera. Por eso lo escrito sin
  importe tampoco se rechaza: se guarda como `nota` igual que lo dictado,
  en el bot y en la web, que la caja de texto es la misma. `POST /apuntes`
  solo devuelve 422 con el texto en blanco: una nota vacía no es nada.

- **El buzón de notas es lo que aún no tiene fecha ni precio.** Una nota
  sigue siendo un `Apunte` de tipo `nota`, no una tabla nueva: lo que se
  dicta por Telegram y lo que se ve en la web tienen que ser la misma fila,
  y el día que fueran dos cosas habría que sincronizarlas. De ahí salen tres
  reglas:
  - **Ponerle fecha la saca del buzón.** `servicios/notas.agendar()` crea la
    cita (heredando el cliente) y borra la nota. Un buzón donde se queda
    todo deja de mirarse a la tercera semana.
  - **En el buzón un número al final no es dinero.** "Cambiar 2 grifos" es
    una tarea. Solo interpreta importes la caja de "Hoy" y el texto libre
    del bot.
  - **Lo cumplido se marca, no se borra** (`Apunte.hecha`, botón ✓ en la web
    y `/hecha <número>` en el bot). "Revisar el coche" cuando ya lo
    revisaste no es un error del que deshacerse, y borrarlo quitaría la
    única prueba de que se hizo. Sale del buzón, se puede abrir aparte y
    devolver. Borrar sigue estando, pero es para lo que se apuntó mal.
  - **Las notas no salen en la lista del día ni en el CSV del gestor**, pero
    sí en la copia de seguridad. Y no disparan el aviso de las 21:00: son
    apuntes, así que si contaran, un recordatorio haría sonar el bot con un
    resumen de 0,00 €. A quien ya lo recibe se le cuentan las que quedan por
    hacer — las hechas no, o el aviso diría "tienes 8 notas" para siempre.

- **Una cita puede durar varios días** (`Cita.fecha_fin`, vacía = un solo
  día). Una reforma de tres días es UNA cosa: se edita, se marca hecha y se
  borra de una vez. El precio es que las consultas miran el rango entero
  (`_ULTIMO_DIA` en `servicios/agenda.py`) — si miraran solo `fecha`, el
  miércoles de una reforma de martes a jueves parecería libre en el
  calendario, que es justo el día en que hace falta saberlo.

- **Las citas se escriben como se hablan.** `/cita 20 septiembre 10am ...`
  ponía la cita en el día de hoy y se tragaba la fecha dentro del título:
  `dominio/parsing_citas.py` solo entendía "20/09" y "10:00". Ahora admite
  el mes por su nombre, el año opcional, "a las", y las horas en formato de
  doce ("10am", "10 pm"). La regla que lo hace seguro es que **nada se
  consume si no se ha entendido**: si "para casa" no es una fecha, esas
  palabras siguen en el título. Y el bot confirma con el día de la semana
  ("Apuntado para el domingo 20/09"), que es lo que hace saltar a la vista
  un día equivocado — una cita en el día que no es se descubre tarde, igual
  que un trabajo colgado de la Ana equivocada.

- **Hábitos: la racha tiene que animar, no castigar.** Cada hábito toca unos
  días de la semana (`Habito.dias`, "01234" es de lunes a viernes) y cada día
  cumplido es una fila en `habitos_hechos`, única por hábito y día para que
  marcar dos veces no cuente doble. Las reglas son funciones puras en
  `dominio/habitos.py`, y las tres que importan: un día que no toca no rompe
  la racha, hoy sin marcar tampoco hasta que acabe el día (si no, amanecería
  rota cada mañana), y los días de antes de empezar no son fallos. El estado
  de cada día (hecho, hoy, fallado, futuro, no_toca, antes) lo calcula el
  backend y la web solo lo pinta: la semana de la lista y el calendario del
  detalle no pueden contar cosas distintas.
  Los recordatorios, a la hora de cada hábito, los decide
  `servicios/habitos.recordatorios_debidos()` y los manda un comprobador
  cada minuto (`bot/habitos.py`), no una tarea por hábito: así lo creado
  desde la web entra solo. Lo ya avisado hoy se guarda en la base
  (`recordado_el`), así que un reinicio no repite; con más de media hora de
  retraso no se mandan, porque un recordatorio tarde es ruido; y
  `/avisos off` los apaga también. El botón "Hecho ✓" del recordatorio solo
  marca, nunca desmarca: si ya se marcó en la web, tocarlo no lo deshace.

- **El parser entiende lo dictado, no solo lo tecleado.** Nadie pronuncia el
  guion de "-45" ni se calla la palabra "euros", así que `dominio/parsing.py`
  admite "120 euros.", "980 €" y "gasto de 45 en gasolina". Con una cautela:
  "gasto de 45 euros" sin concepto se guarda igual como gasto, porque dejarlo
  caer en la regla de trabajo lo apuntaría como dinero que entra, y ese es el
  error que más caro sale.

- **Sin contraseñas.** El acceso a la web usa un token (`TokenAcceso`,
  `servicios/auth.py`) contra el header `Authorization: Bearer`, no
  usuario/contraseña. Falta que el bot lo genere con `/web`
  (`servicios.auth.generar_token()` ya está listo para que ese handler lo
  llame); hasta entonces se genera a mano.

## Cómo se prueba

```
cd backend
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
```

217 tests, medio segundo. `tests/conftest.py` apunta la base a un fichero
temporal **antes** de importar la aplicación, porque `nucleo/db.py` crea el
motor al importarse.

Los tests no son de adorno: cada uno de los tres fallos que ya han ocurrido
tiene el suyo (el error de escala de cien veces en `test_dinero.py`, la
cabecera CORS en los errores en `test_api.py`, y las tildes del CSV en
`test_copias.py`). `test_voz.py` cubre lo que puede romperse en silencio de
las notas de voz: que una nota no cuente como cobrado en el resumen, y que
un fallo del transcriptor se cuente en vez de tragarse.
`test_restauracion.py` genera la copia con la misma función que usa el bot,
para enterarse si cambia su formato, y `test_alarma.py` comprueba que la
alarma calla cuando todo va bien. `test_habitos_reglas.py` fija las reglas
que deciden si una racha anima o desanima, y `test_habitos_bot.py` que el
botón del recordatorio nunca desmarca. Al añadir algo, el test que hace falta es el del caso
que se te ocurra que podría romperse en silencio.

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
  en blanco, marcar cobrado (+404 si no existe), resumen antes/después
  de cobrar, y export a CSV — todo correcto de punta a punta por HTTP.
- `bot/main.py` arranca por **polling** (no webhook: no necesita URL
  pública, y en Railway es otro proceso del mismo repo — ver `Procfile`).
  `bot/handlers.py` tiene `/start`, `/hoy`, `/mes`, `/cobrado <id>`,
  `/web`, un handler de texto libre que anota cualquier mensaje que no
  sea comando, y otro de notas de voz (`filters.VOICE | filters.AUDIO`) que
  las transcribe y las anota igual. `bot/formato.py` solo pinta (importes a la española:
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

- `web/componentes/Notas.tsx` es el buzón: alta, edición en la propia línea
  (cambiar una palabra no merece abrir una ventana) y un modal para ponerle
  fecha, donde se elige día o rango, hora opcional y se retoca el texto —
  que es el momento en que se está pensando en ello. Al agendar salta a la
  agenda para verlo ya puesto.
- `web/` es el front en React: `api.ts` es el único sitio que sabe de HTTP,
  `componentes/Entrada.tsx` pide el token que da `/web` en el bot (se
  guarda en localStorage; si la API lo rechaza, se borra y se vuelve a
  pedir) y `componentes/Panel.tsx` tiene el resumen día/mes, el alta y la
  lista del día con botón de cobrar. El alta usa la misma sintaxis que el
  bot a propósito: quien apunta desde el móvil no aprende dos formas de
  escribir. El CSV se descarga con fetch y no con un `<a href>`, porque la
  ruta exige el header `Authorization`.
- Para que el front pueda llamar a la API hizo falta `GET /apuntes`
  (`listar_apuntes()`) y CORS, con los orígenes en `CORS_ORIGENES`
  (por defecto el Vite de local). Verificado que **todas** las respuestas
  llevan cabecera CORS, incluidos los errores 422 — sin eso el navegador
  bloquea la respuesta y el front no puede enseñar el motivo.

- Todo listo para Railway: `backend/railway.json` (arranca
  `app.api_y_bot:app`), `backend/railpack.json` con el mismo comando,
  `.python-version` con 3.14, y `DESPLIEGUE.md` con los pasos. El
  `railpack.json` no es redundante: Railway solo lee `railway.json` si en el
  panel está puesta su ruta absoluta (no sigue al Root Directory), ese ajuste
  se perdió una vez y los builds empezaron a fallar con "No start command
  detected". Railpack lee `railpack.json` por su cuenta. Si cambia el
  comando, se cambia en los dos. Se quitó el `Procfile`: Railpack no lo usa para Python y
  describía la topología antigua de dos servicios separados. Comprobado
  levantando la app conjunta con uvicorn contra un Telegram de mentira: la
  API responde mientras el bot hace polling —o sea, el bot no bloquea el
  event loop— y el apagado es limpio. También que `sqlite:////data/...`
  resuelve a la ruta absoluta del volumen.

- **Desplegado y funcionando en Railway** (URLs en `DESPLIEGUE.md`). El bot
  se probó contra Telegram de verdad: los apuntes entran con `origen=bot`,
  los importes se guardan en céntimos y `/cobrado` recalcula el resumen. El
  front se probó en el navegador, anotando con `origen=web`.
- El id de Telegram de Yoa es `6529038645`, más del triple del límite del
  `Integer` de 32 bits de Postgres (`2147483647`). Es la confirmación en
  real de por qué `user_id` tiene que ser `BigInteger`: no era una
  precaución teórica.

Pendiente menor: el `.gitignore` de la raíz tiene pegado dentro el
heredoc con el que se creó (`cat > .gitignore <<'EOF'` … `EOF`). Las
líneas de patrón funcionan, las dos sobrantes son inertes.

## Cómo levantarlo en local

```
# backend (desde backend/)
.venv/Scripts/python -m uvicorn app.main:app --reload   # API en :8000
.venv/Scripts/python -m app.bot.main                    # bot, necesita token

# front (desde web/)
npm run dev                                             # Vite en :5173
```

En Windows, Vite escucha en `localhost` por IPv6: `127.0.0.1:5173` no
conecta, `localhost:5173` sí.