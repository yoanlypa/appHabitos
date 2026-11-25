"""Forma de las peticiones y respuestas HTTP. Solo forma, nada de reglas."""
from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

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
    factura_id: int | None = None
    factura_emitida: bool = False
    # De qué trabajo (obra) es, y cómo se llama (para no pedirlo aparte).
    trabajo_id: int | None = None
    trabajo_titulo: str | None = None
    # Solo cobros y gastos sueltos: marcado a mano para la gestoría.
    para_gestoria: bool = False
    # Lo que cuenta: si sale en lo que se manda a la gestoría. Lo decide el
    # backend (dominio/gestoria.py); la web solo lo pinta.
    gestoria: bool = False


class ResumenSalida(BaseModel):
    cobrado: Importe
    pendiente: Importe
    gastos: Importe
    neto: Importe


class ResumenMesSalida(ResumenSalida):
    """Un mes del gráfico anual: los mismos cuatro totales, con su número."""

    mes: int


class ApunteCreado(BaseModel):
    """El apunte y, si el nombre no bastó para decidir, entre quiénes elegir."""

    apunte: ApunteSalida
    candidatos: list["ClienteSalida"] = []


class ApunteCambios(BaseModel):
    concepto: str | None = None
    importe: Decimal | None = None
    pendiente: bool | None = None
    fecha: date | None = None
    tipo: str | None = None  # "trabajo" | "gasto"
    trabajo_id: int | None = None  # mandar null lo saca del trabajo
    para_gestoria: bool | None = None


class AsignarTrabajoEntrada(BaseModel):
    """Varios cobros o gastos a un trabajo (o fuera de él, con null)."""

    apunte_ids: list[int]
    trabajo_id: int | None = None


class MovimientoEntrada(BaseModel):
    """Un trabajo o gasto con los campos ya separados (formulario de Finanzas)."""

    tipo: str
    concepto: str
    importe: Decimal
    fecha: date | None = None
    pendiente: bool = False
    trabajo_id: int | None = None
    para_gestoria: bool = False


class ParteGestoriaSalida(BaseModel):
    """Lo de un periodo repartido en lo que va a la gestoría y lo que no."""

    model_config = ConfigDict(from_attributes=True)

    emitidas: list[ApunteSalida]
    recibidas: list[ApunteSalida]
    trabajos_fuera: list[ApunteSalida]
    gastos_fuera: list[ApunteSalida]
    facturado: Importe
    gastos: Importe
    diferencia: Importe
    sin_documento: int


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
    trabajo_id: int | None = None


class CitaCambios(BaseModel):
    """Lo que se puede corregir de una cita. Solo cambia lo que se manda."""

    titulo: str | None = None
    fecha: date | None = None
    fecha_fin: date | None = None
    hora: time | None = None
    direccion: str | None = None
    notas: str | None = None
    cliente_id: int | None = None
    trabajo_id: int | None = None


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
    trabajo_id: int | None = None


class NotaEntrada(BaseModel):
    texto: str
    trabajo_id: int | None = None  # solo al crearla: la nota de una obra


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
    trabajo_id: int | None = None


class AgendarNota(BaseModel):
    """Ponerle fecha a una nota: deja de ser nota y pasa a la agenda."""

    fecha: date
    fecha_fin: date | None = None
    hora: time | None = None
    titulo: str | None = None  # para retocar el texto al agendarla


class AsignarCliente(BaseModel):
    cliente_id: int | None


class HabitoEntrada(BaseModel):
    nombre: str
    dias: list[int]  # 0 es lunes
    recordar_a: time | None = None


class HabitoCambios(BaseModel):
    """Solo cambia lo que se manda; `recordar_a: null` quita el recordatorio."""

    nombre: str | None = None
    dias: list[int] | None = None
    recordar_a: time | None = None


class MarcarDia(BaseModel):
    fecha: date | None = None  # vacía: hoy
    hecho: bool = True


class HabitoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    dias: list[int]
    inicio: date
    recordar_a: time | None

    @field_validator("dias", mode="before")
    @classmethod
    def _dias_de_texto(cls, valor):
        # En la base van como "01234"; hacia fuera, como lista.
        return [int(c) for c in valor] if isinstance(valor, str) else valor


class DiaHabitoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fecha: date
    estado: str  # hecho | hoy | fallado | futuro | no_toca | antes


class HabitoResumenSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    habito: HabitoSalida
    semana: list[DiaHabitoSalida]
    racha: int
    toca_hoy: bool
    hecho_hoy: bool


class HabitoDetalleSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    habito: HabitoSalida
    racha: int
    mejor_racha: int
    cumplidos: int
    programados: int
    porcentaje: int
    anio: int
    mes: int
    dias_del_mes: list[DiaHabitoSalida]


class TicketLeido(BaseModel):
    """Lo leído en la foto, para rellenar el formulario. Cualquier campo puede faltar."""

    factura_id: int
    total: Importe | None
    fecha: date | None
    comercio: str | None
    iva: Importe | None
    concepto: str
    # Si es una factura que emite Yoa: a quién, cuánto entra de verdad (sin
    # la retención) y qué trabajos pendientes podrían ser el suyo.
    emitida: bool = False
    cliente: str | None = None
    a_cobrar: Importe | None = None
    candidatos: list[ApunteSalida] = []


class FacturaEmitidaEntrada(BaseModel):
    apunte_id: int | None = None  # None: trabajo nuevo
    cobrada: bool = False
    concepto: str = ""
    importe: Decimal | None = None
    fecha: date | None = None


class GastoDeFactura(BaseModel):
    concepto: str
    importe: Decimal
    fecha: date | None = None
    trabajo_id: int | None = None
    para_gestoria: bool = False


class AjustesSalida(BaseModel):
    avisos_activos: bool
    correo: str | None
    # Si el servidor sabe mandar correos (está la clave de Resend).
    correo_disponible: bool
    # Con cuántos minutos de antelación se avisa de una cita ese mismo día.
    aviso_cita_minutos: int


class AjustesCambios(BaseModel):
    correo: str | None = None  # null o vacío lo quita


# ---------- Trabajos (obras) ----------


class TrabajoEntrada(BaseModel):
    titulo: str
    cliente_id: int | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    facturado: bool = False
    resena: bool = False
    descripcion: str | None = None


class TrabajoCambios(BaseModel):
    """Solo cambia lo que se manda; null en cliente o fechas lo vacía."""

    titulo: str | None = None
    cliente_id: int | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    facturado: bool | None = None
    resena: bool | None = None
    descripcion: str | None = None


class TrabajoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    titulo: str
    descripcion: str | None
    cliente_id: int | None
    cliente: ClienteSalida | None = None
    fecha_inicio: date | None
    fecha_fin: date | None
    facturado: bool
    resena: bool


class CuentasSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cobrado: Importe
    pendiente: Importe
    gastos: Importe
    ingresos: Importe
    beneficio: Importe


class TrabajoListadoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trabajo: TrabajoSalida
    cuentas: CuentasSalida
    notas_pendientes: int
    proxima_cita: CitaSalida | None


class FichaTrabajoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trabajo: TrabajoSalida
    cuentas: CuentasSalida
    movimientos: list[ApunteSalida]
    notas: list[NotaSalida]
    citas: list[CitaSalida]


# --- Casa -------------------------------------------------------------------


class MiembroSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    nombre: str
    titular: bool
    efectivo: bool


class CasaSalida(BaseModel):
    """Quién soy en la casa y quién más hay. `solo_casa`: la web enseña solo Casa."""

    hogar_id: int
    nombre: str
    yo: MiembroSalida
    miembros: list[MiembroSalida]
    solo_casa: bool
    categorias: list[str]
    hay_recetas: bool


class InvitacionSalida(BaseModel):
    codigo: str
    dias: int


class PersonaQueVuelve(BaseModel):
    """Alguien de la casa que entró solo por la web y puede volver a ser él."""

    id: int
    nombre: str


class InvitacionVista(BaseModel):
    casa: str
    miembros: list[str]
    volver: list[PersonaQueVuelve] = []


class UnirseEntrada(BaseModel):
    codigo: str
    nombre: str = ""
    # Si se elige "Soy …" en la lista de quienes ya estaban.
    miembro_id: int | None = None


class UnirseSalida(BaseModel):
    token: str


class NombreEntrada(BaseModel):
    nombre: str | None = None
    efectivo: bool | None = None  # cómo paga casi siempre


class GastoCasaEntrada(BaseModel):
    concepto: str
    importe: Decimal
    fecha: date | None = None
    categoria: str | None = None
    pagado_por: int | None = None
    efectivo: bool | None = None


class GastoCasaTexto(BaseModel):
    texto: str


class GastoCasaCambios(BaseModel):
    concepto: str | None = None
    importe: Decimal | None = None
    fecha: date | None = None
    categoria: str | None = None
    pagado_por: int | None = None
    efectivo: bool | None = None


class GastoCasaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    fecha: date
    concepto: str
    importe: Importe
    categoria: str
    origen: str
    efectivo: bool


class ParteSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    total: Importe


class ResumenCasaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: Importe
    anterior: Importe
    por_categoria: list[ParteSalida]
    por_persona: list[ParteSalida]
    efectivo: Importe
    sin_detallar: Importe


class CarteraSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    nombre: str
    esperado: Importe | None
    contado_el: date | None
    entradas: Importe
    gastado: Importe


class ImporteEntrada(BaseModel):
    importe: Decimal


class MovimientoCarteraSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fecha: date
    tipo: str
    importe: Importe
    gasto_id: int | None


class RecuentoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    esperado: Importe | None
    contado: Importe
    sin_detallar: Importe
    sobra: Importe


class ArticuloEntrada(BaseModel):
    texto: str


class ArticuloCambios(BaseModel):
    hay: bool | None = None
    texto: str | None = None


class ArticuloSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    texto: str
    hay: bool
    anadido_por: int | None


class RecetasEntrada(BaseModel):
    preferencias: str = ""


class RecetaSalida(BaseModel):
    nombre: str
    minutos: int | None
    usa: list[str]
    falta: list[str]
    pasos: list[str]


# --- Importar varios movimientos desde la web -------------------------------


class MovimientoImportado(BaseModel):
    """Un movimiento leído de una lista, un CSV, un Excel o una captura.

    `tipo` puede venir vacío: una tabla sin columna de tipo y sin signos no
    dice si son gastos o cobros, y eso se pregunta, no se supone.
    `repetido`: mismo día, tipo e importe que algo que ya está. Se enseña y
    se puede meter igual.
    """

    fecha: date
    tipo: str | None = None
    concepto: str
    importe: Importe
    pendiente: bool = False
    repetido: bool = False


class LecturaImportacion(BaseModel):
    movimientos: list[MovimientoImportado]
    falta_tipo: bool


class RevisarImportacion(BaseModel):
    movimientos: list[MovimientoImportado]
    # El que se ha elegido para los que no lo traían.
    tipo: str | None = None


class ConfirmarImportacion(BaseModel):
    movimientos: list[MovimientoImportado]
    # True cuando se han elegido a mano también algunos de los repetidos: entonces
    # entra exactamente lo elegido. Con False se vuelve a mirar qué está ya.
    todo: bool = False


class ImportacionHecha(BaseModel):
    apuntes: list[ApunteSalida]
    ya_estaban: int


class DeshacerImportacion(BaseModel):
    ids: list[int]


class Deshecha(BaseModel):
    borrados: int
