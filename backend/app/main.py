"""Punto de entrada de la API: crea la app FastAPI, las tablas y monta los routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import apuntes, export, resumen
from app.nucleo.config import CORS_ORIGENES
from app.nucleo.db import crear_tablas


@asynccontextmanager
async def lifespan(_app: FastAPI):
    crear_tablas()
    yield


app = FastAPI(title="Parte del día", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGENES,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(apuntes.router)
app.include_router(resumen.router)
app.include_router(export.router)


@app.get("/salud")
def salud():
    return {"estado": "ok"}
