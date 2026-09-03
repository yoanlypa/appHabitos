"""Punto de entrada de la API: crea la app FastAPI, las tablas y monta los routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import apuntes, export, resumen
from app.nucleo.db import crear_tablas


@asynccontextmanager
async def lifespan(_app: FastAPI):
    crear_tablas()
    yield


app = FastAPI(title="Parte del día", lifespan=lifespan)

app.include_router(apuntes.router)
app.include_router(resumen.router)
app.include_router(export.router)


@app.get("/salud")
def salud():
    return {"estado": "ok"}
