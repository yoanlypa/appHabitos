"""Forma de las peticiones y respuestas HTTP. Solo forma, nada de reglas."""
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ApunteEntrada(BaseModel):
    texto: str
    origen: str  # "web" | "bot"


class ApunteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    tipo: str
    concepto: str
    importe: Decimal
    pendiente: bool
    origen: str
    creado: datetime


class ResumenSalida(BaseModel):
    cobrado: Decimal
    pendiente: Decimal
    gastos: Decimal
    neto: Decimal
