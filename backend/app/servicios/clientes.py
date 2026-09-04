"""Casos de uso de clientes: darlos de alta, buscarlos y ver su ficha.

La ficha es el porqué de todo esto: antes "Ana" era texto suelto dentro del
concepto y no había forma de saber qué le habías hecho ni qué te debía.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dominio.deteccion_clientes import Candidato, buscar_clientes
from app.dominio.models import Apunte, Cita, Cliente


class ClienteNoEncontrado(LookupError):
    """No existe ese cliente para ese usuario."""


@dataclass
class ClienteConDeuda:
    cliente: Cliente
    debe: Decimal          # trabajos suyos sin cobrar
    total_trabajos: int


@dataclass
class FichaCliente:
    cliente: Cliente
    debe: Decimal
    cobrado: Decimal
    apuntes: list[Apunte]
    citas: list[Cita]


def crear_cliente(
    db: Session,
    user_id: int,
    nombre: str,
    telefono: str | None = None,
    direccion: str | None = None,
    notas: str | None = None,
) -> Cliente:
    cliente = Cliente(
        user_id=user_id,
        nombre=nombre.strip(),
        telefono=(telefono or None),
        direccion=(direccion or None),
        notas=(notas or None),
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def _suyo(db: Session, user_id: int, cliente_id: int) -> Cliente:
    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == cliente_id, Cliente.user_id == user_id)
        .first()
    )
    if cliente is None:
        raise ClienteNoEncontrado(f"el cliente {cliente_id} no existe para {user_id}")
    return cliente


def actualizar_cliente(db: Session, user_id: int, cliente_id: int, **campos) -> Cliente:
    cliente = _suyo(db, user_id, cliente_id)
    for campo in ("nombre", "telefono", "direccion", "notas"):
        if campo in campos and campos[campo] is not None:
            setattr(cliente, campo, campos[campo] or None)
    db.commit()
    db.refresh(cliente)
    return cliente


def borrar_cliente(db: Session, user_id: int, cliente_id: int) -> None:
    """Borra el cliente pero deja sus apuntes: son dinero, no se tiran."""
    cliente = _suyo(db, user_id, cliente_id)
    db.query(Apunte).filter(Apunte.cliente_id == cliente_id).update({"cliente_id": None})
    db.query(Cita).filter(Cita.cliente_id == cliente_id).update({"cliente_id": None})
    db.delete(cliente)
    db.commit()


def listar_clientes(db: Session, user_id: int, buscar: str | None = None) -> list[ClienteConDeuda]:
    """Todos los clientes con lo que debe cada uno, de mayor deuda a menor.

    Quien más te debe, primero: es el orden en el que de verdad se mira esta
    lista.
    """
    consulta = db.query(Cliente).filter(Cliente.user_id == user_id)
    if buscar:
        consulta = consulta.filter(Cliente.nombre.ilike(f"%{buscar.strip()}%"))
    clientes = consulta.order_by(Cliente.nombre).all()

    # Una sola consulta para las deudas, en vez de una por cliente.
    # func.sum() ya devuelve euros: el tipo Centimos se aplica también al
    # agregado, así que aquí NO hay que volver a dividir entre 100.
    deudas = dict(
        db.query(Apunte.cliente_id, func.sum(Apunte.importe))
        .filter(
            Apunte.user_id == user_id,
            Apunte.tipo == "trabajo",
            Apunte.pendiente.is_(True),
            Apunte.cliente_id.isnot(None),
        )
        .group_by(Apunte.cliente_id)
        .all()
    )
    cuentas = dict(
        db.query(Apunte.cliente_id, func.count(Apunte.id))
        .filter(
            Apunte.user_id == user_id,
            Apunte.tipo == "trabajo",
            Apunte.cliente_id.isnot(None),
        )
        .group_by(Apunte.cliente_id)
        .all()
    )

    resultado = [
        ClienteConDeuda(
            cliente=c,
            debe=deudas.get(c.id) or Decimal("0"),
            total_trabajos=cuentas.get(c.id, 0),
        )
        for c in clientes
    ]
    resultado.sort(key=lambda x: (-x.debe, x.cliente.nombre.lower()))
    return resultado


def ficha_cliente(db: Session, user_id: int, cliente_id: int) -> FichaCliente:
    cliente = _suyo(db, user_id, cliente_id)
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.cliente_id == cliente_id)
        .order_by(Apunte.fecha.desc(), Apunte.id.desc())
        .all()
    )
    citas = (
        db.query(Cita)
        .filter(Cita.user_id == user_id, Cita.cliente_id == cliente_id)
        .order_by(Cita.fecha.desc())
        .all()
    )
    debe = sum((a.importe for a in apuntes if a.tipo == "trabajo" and a.pendiente), Decimal("0"))
    cobrado = sum(
        (a.importe for a in apuntes if a.tipo == "trabajo" and not a.pendiente), Decimal("0")
    )
    return FichaCliente(cliente=cliente, debe=debe, cobrado=cobrado, apuntes=apuntes, citas=citas)


def asignar_cliente(db: Session, user_id: int, apunte_id: int, cliente_id: int | None) -> Apunte:
    """Cuelga un apunte ya escrito de un cliente, o lo suelta si va None."""
    apunte = (
        db.query(Apunte)
        .filter(Apunte.id == apunte_id, Apunte.user_id == user_id)
        .first()
    )
    if apunte is None:
        raise LookupError(f"el apunte {apunte_id} no existe para {user_id}")
    if cliente_id is not None:
        _suyo(db, user_id, cliente_id)
    apunte.cliente_id = cliente_id
    db.commit()
    db.refresh(apunte)
    return apunte


def pendientes_de_cobro(db: Session, user_id: int) -> list[Apunte]:
    """Lo que te deben, lo más viejo primero: es lo que más urge reclamar."""
    return (
        db.query(Apunte)
        .filter(
            Apunte.user_id == user_id,
            Apunte.tipo == "trabajo",
            Apunte.pendiente.is_(True),
        )
        .order_by(Apunte.fecha.asc(), Apunte.id.asc())
        .all()
    )


def clientes_mencionados(db: Session, user_id: int, texto: str) -> list[Cliente]:
    """Los clientes que aparecen nombrados en un texto de apunte.

    Ninguno, uno (se asigna sin preguntar) o varios (hay que preguntar).
    """
    suyos = db.query(Cliente).filter(Cliente.user_id == user_id).all()
    if not suyos:
        return []
    encontrados = buscar_clientes(texto, [Candidato(c.id, c.nombre) for c in suyos])
    por_id = {c.id: c for c in suyos}
    return [por_id[c.id] for c in encontrados]
