"""Casos de uso de los trabajos (las obras): crear, ver, cambiar y borrar.

Un trabajo es la ficha que junta todo lo de una obra, como una página de
Notion: cliente, fechas, si lo factura Yoa, si el cliente dejó reseña, y
dentro sus cobros, gastos, notas y citas. Las cuentas de cada trabajo
(cobrado, gastado, lo que queda) se hacen aquí, no en la web.

Borrar un trabajo no borra nada de lo que tiene dentro: se queda suelto.
Un gasto que justificaba una factura no puede desaparecer porque se borró la
carpeta. Y lo que iba a la gestoría por ser de un trabajo facturado se queda
marcado a mano: nada sale de lo que se manda sin que se vea.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte, Cita, Cliente, Trabajo
from app.nucleo.tiempo import hoy_local
from app.servicios.clientes import clientes_mencionados


class TrabajoNoEncontrado(LookupError):
    """No existe ese trabajo para ese usuario."""


class TrabajoNoValido(ValueError):
    """Lo que se quiere guardar no tiene sentido (sin título, fechas al revés)."""


_SIN_TOCAR = object()  # None es un valor válido: "quítale el cliente", "sin fecha de fin"


def trabajo_suyo(db: Session, user_id: int, trabajo_id: int) -> Trabajo:
    trabajo = (
        db.query(Trabajo).filter(Trabajo.id == trabajo_id, Trabajo.user_id == user_id).first()
    )
    if trabajo is None:
        raise TrabajoNoEncontrado(f"el trabajo {trabajo_id} no existe")
    return trabajo


def _cliente_suyo(db: Session, user_id: int, cliente_id: int | None) -> None:
    if cliente_id is None:
        return
    if not db.query(Cliente).filter(Cliente.id == cliente_id, Cliente.user_id == user_id).first():
        raise TrabajoNoValido("ese cliente no existe")


def _comprobar(trabajo: Trabajo) -> None:
    if not (trabajo.titulo or "").strip():
        raise TrabajoNoValido("el trabajo necesita un nombre")
    if trabajo.fecha_inicio and trabajo.fecha_fin and trabajo.fecha_fin < trabajo.fecha_inicio:
        raise TrabajoNoValido("la fecha de fin no puede ser antes de la de inicio")


def crear_trabajo(
    db: Session,
    user_id: int,
    titulo: str,
    cliente_id: int | None = None,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    facturado: bool = False,
    resena: bool = False,
    descripcion: str | None = None,
) -> Trabajo:
    _cliente_suyo(db, user_id, cliente_id)
    trabajo = Trabajo(
        user_id=user_id,
        titulo=(titulo or "").strip(),
        cliente_id=cliente_id,
        # Sin decir nada, empieza hoy: es lo normal al darlo de alta.
        fecha_inicio=fecha_inicio or hoy_local(),
        fecha_fin=fecha_fin,
        facturado=facturado,
        resena=resena,
        descripcion=(descripcion or "").strip() or None,
    )
    _comprobar(trabajo)
    db.add(trabajo)
    db.commit()
    db.refresh(trabajo)
    return trabajo


def actualizar_trabajo(
    db: Session,
    user_id: int,
    trabajo_id: int,
    titulo: str | None = None,
    cliente_id=_SIN_TOCAR,
    fecha_inicio=_SIN_TOCAR,
    fecha_fin=_SIN_TOCAR,
    facturado: bool | None = None,
    resena: bool | None = None,
    descripcion=_SIN_TOCAR,
) -> Trabajo:
    """Cambia solo lo que se pase. Los que se pueden vaciar usan un centinela."""
    trabajo = trabajo_suyo(db, user_id, trabajo_id)
    if titulo is not None:
        trabajo.titulo = titulo.strip()
    if cliente_id is not _SIN_TOCAR:
        _cliente_suyo(db, user_id, cliente_id)
        trabajo.cliente_id = cliente_id
    if fecha_inicio is not _SIN_TOCAR:
        trabajo.fecha_inicio = fecha_inicio
    if fecha_fin is not _SIN_TOCAR:
        trabajo.fecha_fin = fecha_fin
    if facturado is not None:
        trabajo.facturado = facturado
    if resena is not None:
        trabajo.resena = resena
    if descripcion is not _SIN_TOCAR:
        trabajo.descripcion = (descripcion or "").strip() or None
    _comprobar(trabajo)
    db.commit()
    db.refresh(trabajo)
    return trabajo


def borrar_trabajo(db: Session, user_id: int, trabajo_id: int) -> None:
    """Borra la ficha y deja suelto lo que tenía dentro, sin perder nada."""
    trabajo = trabajo_suyo(db, user_id, trabajo_id)
    for apunte in list(trabajo.apuntes):
        if apunte.tipo in ("trabajo", "gasto"):
            # Conserva lo que valía para la gestoría.
            apunte.para_gestoria = apunte.para_gestoria or bool(trabajo.facturado)
        apunte.trabajo_id = None
    for cita in list(trabajo.citas):
        cita.trabajo_id = None
    db.delete(trabajo)
    db.commit()


@dataclass
class Cuentas:
    """Las cuentas de un trabajo: lo cobrado, lo que falta por cobrar y lo gastado."""

    cobrado: Decimal = Decimal("0")
    pendiente: Decimal = Decimal("0")
    gastos: Decimal = Decimal("0")

    @property
    def ingresos(self) -> Decimal:
        return self.cobrado + self.pendiente

    @property
    def beneficio(self) -> Decimal:
        """Lo que queda: todo lo que entra (cobrado o no) menos lo gastado."""
        return self.ingresos - self.gastos


def _cuentas(apuntes: list[Apunte]) -> Cuentas:
    c = Cuentas()
    for a in apuntes:
        if a.tipo == "trabajo" and a.pendiente:
            c.pendiente += a.importe
        elif a.tipo == "trabajo":
            c.cobrado += a.importe
        elif a.tipo == "gasto":
            c.gastos += a.importe
    return c


@dataclass
class TrabajoListado:
    trabajo: Trabajo
    cuentas: Cuentas
    notas_pendientes: int
    proxima_cita: Cita | None


def listar_trabajos(db: Session, user_id: int) -> list[TrabajoListado]:
    """Todos, del más reciente al más viejo, con sus cuentas ya hechas."""
    hoy = hoy_local()
    trabajos = (
        db.query(Trabajo)
        .filter(Trabajo.user_id == user_id)
        .order_by(Trabajo.fecha_inicio.desc().nullslast(), Trabajo.id.desc())
        .all()
    )
    resultado = []
    for t in trabajos:
        citas = [c for c in t.citas if not c.hecha and (c.fecha_fin or c.fecha) >= hoy]
        resultado.append(
            TrabajoListado(
                trabajo=t,
                cuentas=_cuentas(t.apuntes),
                notas_pendientes=sum(1 for a in t.apuntes if a.tipo == "nota" and not a.hecha),
                proxima_cita=min(citas, key=lambda c: (c.fecha, c.hora is None, c.hora), default=None),
            )
        )
    return resultado


@dataclass
class FichaTrabajo:
    """Un trabajo abierto: todo lo que tiene dentro, ya repartido."""

    trabajo: Trabajo
    cuentas: Cuentas
    movimientos: list[Apunte] = field(default_factory=list)
    notas: list[Apunte] = field(default_factory=list)
    citas: list[Cita] = field(default_factory=list)


def ficha_trabajo(db: Session, user_id: int, trabajo_id: int) -> FichaTrabajo:
    trabajo = trabajo_suyo(db, user_id, trabajo_id)
    apuntes = list(trabajo.apuntes)
    return FichaTrabajo(
        trabajo=trabajo,
        cuentas=_cuentas(apuntes),
        # El más reciente arriba, como en Finanzas.
        movimientos=sorted(
            (a for a in apuntes if a.tipo in ("trabajo", "gasto")),
            key=lambda a: (a.fecha, a.id),
            reverse=True,
        ),
        # Lo pendiente primero; lo hecho al final, sin borrarlo.
        notas=sorted((a for a in apuntes if a.tipo == "nota"), key=lambda a: (a.hecha, -a.id)),
        citas=sorted(trabajo.citas, key=lambda c: (c.fecha, c.hora is None, c.hora)),
    )


# --- Desde el bot -------------------------------------------------------------


def terminado(trabajo: Trabajo, hoy: date | None = None) -> bool:
    """Terminado es tener fecha de fin y que ya haya pasado (como en la web)."""
    hoy = hoy or hoy_local()
    return trabajo.fecha_fin is not None and trabajo.fecha_fin < hoy


def en_curso(db: Session, user_id: int) -> list[Trabajo]:
    """Los trabajos sin terminar, el más reciente primero.

    Es la lista que se ofrece al tocar "📁 Trabajo" bajo un apunte: lo
    terminado no se ofrece, porque un gasto nuevo casi nunca es de una obra
    acabada, y una lista larga obliga a leer.
    """
    hoy = hoy_local()
    return [
        t
        for t in db.query(Trabajo)
        .filter(Trabajo.user_id == user_id)
        .order_by(Trabajo.fecha_inicio.desc().nullslast(), Trabajo.id.desc())
        .all()
        if not terminado(t, hoy)
    ]


@dataclass
class TrabajoNuevo:
    trabajo: Trabajo
    # Si el nombre nombra a varios clientes posibles (dos Anas), hay que preguntar.
    candidatos: list[Cliente] = field(default_factory=list)


def crear_por_texto(db: Session, user_id: int, texto: str) -> TrabajoNuevo:
    """Un trabajo a partir de lo escrito: "Reforma baño Ana Ruiz".

    Empieza hoy. El cliente se reconoce como al anotar: si el nombre de un
    cliente de alta sale en el texto y es uno solo, queda puesto; si son
    varios, se devuelven para preguntar, y no se adivina. El nombre del
    trabajo se queda tal cual se escribió: "Reforma baño Ana Ruiz" dice más
    en una lista que "Reforma baño".
    """
    titulo = (texto or "").strip()
    if not titulo:
        raise TrabajoNoValido("el trabajo necesita un nombre")
    candidatos = clientes_mencionados(db, user_id, titulo)
    trabajo = crear_trabajo(
        db,
        user_id,
        titulo,
        cliente_id=candidatos[0].id if len(candidatos) == 1 else None,
        fecha_inicio=hoy_local(),
    )
    return TrabajoNuevo(trabajo=trabajo, candidatos=candidatos if len(candidatos) > 1 else [])
