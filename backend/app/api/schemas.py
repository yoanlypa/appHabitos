"""Forma de las peticiones y respuestas HTTP. Solo forma, nada de reglas."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

# Los importes salen siempre con dos decimales. Sin esto, un mismo listado
# mezcla "120", "45.5" y "980.50", que en el CSV que va al gestor queda como
# si estuvieran mal apuntados.
Importe = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]


class ApunteEntrada(BaseModel):
    texto: str
    origen: str  # "web" | "bot"


class ApunteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    tipo: str
    concepto: str
    importe: Importe
    pendiente: bool
    origen: str
    creado: datetime
    cliente_id: int | None = None


class ResumenSalida(BaseModel):
    cobrado: Importe
    pendiente: Importe
    gastos: Importe
    neto: Importe


class ApunteCreado(BaseModel):
    """El apunte y, si el nombre no bastó para decidir, entre quiénes elegir."""

    apunte: ApunteSalida
    candidatos: list["ClienteSalida"] = []


class ApunteCambios(BaseModel):
    concepto: str | None = None
    importe: Decimal | None = None
    pendiente: bool | None = None
    fecha: date | None = None


class TrimestreSalida(BaseModel):
    anio: int
    trimestre: int
    desde: date
    hasta: date
    cobrado: Importe
    pendiente: Importe
    gastos: Importe
    neto: Importe
    estimacion_130: Importe


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
    debe: Importe
    total_trabajos: int


class FichaClienteSalida(BaseModel):
    cliente: ClienteSalida
    debe: Importe
    cobrado: Importe
    apuntes: list[ApunteSalida]
    citas: list["CitaSalida"]


class CitaEntrada(BaseModel):
    fecha: date
    titulo: str
    fecha_fin: date | None = None  # vacía: empieza y acaba el mismo día
    hora: time | None = None
    direccion: str | None = None
    cliente_id: int | None = None
    notas: str | None = None


class CitaCambios(BaseModel):
    """Lo que se puede corregir de una cita. Solo cambia lo que se manda."""

    titulo: str | None = None
    fecha: date | None = None
    fecha_fin: date | None = None
    hora: time | None = None
    direccion: str | None = None
    notas: str | None = None
    cliente_id: int | None = None


class CitaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    fecha_fin: date | None
    hora: time | None
    titulo: str
    direccion: str | None
    notas: str | None
    hecha: bool
    cliente_id: int | None
    cliente: ClienteSalida | None = None


class NotaEntrada(BaseModel):
    texto: str


class NotaSalida(BaseModel):
    """Una nota del buzón. Por debajo es un apunte de tipo "nota"."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date  # el día en que se apuntó, no el día en que toca
    concepto: str
    hecha: bool
    origen: str
    creado: datetime
    cliente_id: int | None = None
    cliente: ClienteSalida | None = None


class AgendarNota(BaseModel):
    """Ponerle fecha a una nota: deja de ser nota y pasa a la agenda."""

    fecha: date
    fecha_fin: date | None = None
    hora: time | None = None
    titulo: str | None = None  # para retocar el texto al agendarla


class AsignarCliente(BaseModel):
    cliente_id: int | None
