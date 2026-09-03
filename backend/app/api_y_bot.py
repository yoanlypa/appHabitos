"""Entrypoint de Railway: la API y el bot en el mismo proceso.

Railway no deja compartir un volumen entre servicios, y estos dos tienen que
leer y escribir la misma base SQLite. Separarlos daría a cada uno su propio
disco: lo que anotaras por Telegram no saldría en la web.

Así que en producción viven juntos — un servicio, un volumen, una base — y
el precio es que un redespliegue reinicia los dos. En local se siguen
arrancando por separado (`app.main:app` y `python -m app.bot.main`).
"""
from app.main import crear_api

app = crear_api(con_bot=True)
