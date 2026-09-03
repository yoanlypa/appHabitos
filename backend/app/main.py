"""Punto de entrada de la API: crea la app FastAPI, las tablas y monta los routers.

`crear_api()` acepta llevar el bot dentro del mismo proceso, que es como se
despliega en Railway (ver `app/api_y_bot.py`). Por defecto no lo lleva: en
local se arrancan por separado.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import apuntes, export, resumen
from app.nucleo.config import CORS_ORIGENES
from app.nucleo.db import crear_tablas


def crear_api(con_bot: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        crear_tablas()
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
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    api.include_router(apuntes.router)
    api.include_router(resumen.router)
    api.include_router(export.router)

    @api.get("/salud")
    def salud():
        return {"estado": "ok"}

    return api


app = crear_api()
