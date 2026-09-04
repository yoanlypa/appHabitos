"""Forma de las peticiones y respuestas HTTP. Solo forma, nada de reglas."""
from datetime import date, datetime, time
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
    cliente_id: int | None = None


class ResumenSalida(BaseModel):
    cobrado: Decimal
    pendiente: Decimal
    gastos: Decimal
    neto: Decimal


class ApunteCreado(BaseModel):
    """El apunte y, si el nombre no bastó para decidir, entre quiénes elegir."""

    apunte: ApunteSalida
    candidatos: list["ClienteSalida"] = []


class ClienteEntrada(BaseModel):
    nombre: str
    telefono: str | None = None
    direccion: str | None = None
    notas: str | None = None


class ClienteCambios(BaseModel):
    nombre: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    notas: str | None = None


class ClienteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    telefono: str | None
    direccion: str | None
    notas: str | None


class ClienteListado(BaseModel):
    """El cliente más lo que debe: es como se mira la lista."""

    cliente: ClienteSalida
    debe: Decimal
    total_trabajos: int


class FichaClienteSalida(BaseModel):
    cliente: ClienteSalida
    debe: Decimal
    cobrado: Decimal
    apuntes: list[ApunteSalida]
    citas: list["CitaSalida"]


class CitaEntrada(BaseModel):
    fecha: date
    titulo: str
    hora: time | None = None
    direccion: str | None = None
    cliente_id: int | None = None
    notas: str | None = None


class CitaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    hora: time | None
    titulo: str
    direccion: str | None
    notas: str | None
    hecha: bool
    cliente_id: int | None
    cliente: ClienteSalida | None = None


class AsignarCliente(BaseModel):
    cliente_id: int | None
