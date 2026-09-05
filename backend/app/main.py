"""Punto de entrada de la API: crea la app FastAPI, las tablas y monta los routers.

`crear_api()` acepta llevar el bot dentro del mismo proceso, que es como se
despliega en Railway (ver `app/api_y_bot.py`). Por defecto no lo lleva: en
local se arrancan por separado.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agenda, apuntes, clientes, export, resumen
from app.nucleo.almacenamiento import avisar_si_es_efimera, estado as estado_almacenamiento
from app.nucleo.config import CORS_ORIGENES
from app.nucleo.migraciones import migrar


def crear_api(con_bot: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        avisar_si_es_efimera()
        migrar()
        if not con_bot:
            yield
            return
        # Se importa aquí para no arrastrar telegram cuando solo se sirve la API.
        from app.bot.main import en_marcha

        async with en_marcha():
            yield

    api = FastAPI(title="Parte del día", lifespan=lifespan)

    api.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGENES,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api.include_router(apuntes.router)
    api.include_router(clientes.router)
    api.include_router(clientes.otros)
    api.include_router(agenda.router)
    api.include_router(resumen.router)
    api.include_router(export.router)

    @api.get("/salud")
    def salud():
        """Estado del servicio y, sobre todo, si los datos van a sobrevivir.

        Lo segundo se mira desde fuera a propósito: cuando la base se guarda
        dentro del contenedor la app arranca igual, sólo que vacía, y sin
        esto no hay forma de darse cuenta hasta perder el trabajo de días.
        """
        almacen = estado_almacenamiento()
        return {
            "estado": "ok",
            "datos": {
                "motor": almacen.motor,
                "ruta": almacen.ruta,
                "persistente": almacen.persistente,
                "existe": almacen.existe,
                "tamano_bytes": almacen.tamano_bytes,
                "aviso": almacen.aviso,
            },
        }

    return api


app = crear_api()
