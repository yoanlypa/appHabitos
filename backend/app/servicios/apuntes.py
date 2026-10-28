"""Casos de uso sobre apuntes: crear, listar y marcar cobrado.

Única capa que toca la base de datos, y solo a través de `dominio/`. `api/`
y `bot/` llaman aquí; si un handler hiciera esto directamente, la lógica
estaría mal colocada.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte
from app.nucleo import archivos
from app.dominio.parsing import TextoNoInterpretable, interpretar_texto
from app.dominio.tickets import fecha_escrita
from app.nucleo.tiempo import hoy_local
from app.servicios.clientes import clientes_mencionados


class ApunteNoEncontrado(LookupError):
    """No existe un apunte con ese id para ese usuario."""


def crear_apunte(
    db: Session, user_id: int, texto: str, origen: str, cliente_id: int | None = None
) -> Apunte:
    interpretado = interpretar_texto(texto)
    apunte = Apunte(
        user_id=user_id,
        fecha=hoy_local(),
        tipo=interpretado.tipo,
        concepto=interpretado.concepto,
        importe=interpretado.importe,
        pendiente=interpretado.pendiente,
        origen=origen,
        cliente_id=cliente_id,
    )
    db.add(apunte)
    db.commit()
    db.refresh(apunte)
    return apunte


def crear_nota(
    db: Session, user_id: int, texto: str, origen: str, cliente_id: int | None = None
) -> Apunte:
    """Un apunte sin dinero: "llamar a Ana el martes".

    Nace con las notas de voz, donde no todo lo que se dicta es un trabajo o
    un gasto, y perder lo dictado por no llevar importe sería peor que
    guardarlo. Importe 0 y tipo "nota", que los resúmenes no suman.
    """
    apunte = Apunte(
        user_id=user_id,
        fecha=hoy_local(),
        tipo="nota",
        concepto=texto.strip(),
        importe=Decimal("0"),
        pendiente=False,
        origen=origen,
        cliente_id=cliente_id,
    )
    db.add(apunte)
    db.commit()
    db.refresh(apunte)
    return apunte


def listar_apuntes(
    db: Session, user_id: int, fecha: date | None = None, incluir_notas: bool = False
) -> list[Apunte]:
    """Los apuntes de un día, el más reciente primero (que es como se miran).

    Sin las notas: esta lista es la del dinero del día, y las notas tienen
    su propio buzón (`servicios/notas.py`), donde siguen estando aunque
    sean de la semana pasada. Salir en los dos sitios sería duplicarlas.
    """
    consulta = db.query(Apunte).filter(
        Apunte.user_id == user_id, Apunte.fecha == (fecha or hoy_local())
    )
    if not incluir_notas:
        consulta = consulta.filter(Apunte.tipo != "nota")
    return consulta.order_by(Apunte.id.desc()).all()


def movimientos(db: Session, user_id: int, desde: date, hasta: date) -> list[Apunte]:
    """Trabajos y gastos entre dos fechas, incluidas, el más reciente primero.

    Para la pantalla de Finanzas. Sin notas, igual que la lista del día:
    aquí se mira el dinero, y una nota no lleva.
    """
    return (
        db.query(Apunte)
        .filter(
            Apunte.user_id == user_id,
            Apunte.fecha >= desde,
            Apunte.fecha <= hasta,
            Apunte.tipo != "nota",
        )
        .order_by(Apunte.fecha.desc(), Apunte.id.desc())
        .all()
    )


def _suyo(db: Session, user_id: int, apunte_id: int) -> Apunte:
    apunte = (
        db.query(Apunte)
        .filter(Apunte.id == apunte_id, Apunte.user_id == user_id)
        .first()
    )
    if apunte is None:
        raise ApunteNoEncontrado(f"apunte {apunte_id} no existe para el usuario {user_id}")
    return apunte


def borrar_apunte(db: Session, user_id: int, apunte_id: int) -> Apunte:
    """Borra un apunte. Se devuelve el borrado para poder decir qué se fue.

    Hace falta de verdad: se apunta con una mano en mitad de un trabajo y se
    escribe 1200 donde iba 120. Sin esto, el error se queda en las cuentas
    para siempre.
    """
    apunte = _suyo(db, user_id, apunte_id)
    # Un gasto escaneado se lleva su foto: dejarla sería una factura suelta
    # que ya no justifica nada, y la fila apuntaría a un apunte que no existe.
    if apunte.factura is not None:
        archivos.borrar(apunte.factura.ruta)
        db.delete(apunte.factura)
    db.delete(apunte)
    db.commit()
    return apunte


class MovimientoNoValido(ValueError):
    """Lo que se quiere guardar no es un trabajo o gasto que tenga sentido."""


_TIPOS_DE_DINERO = ("trabajo", "gasto")


def _validar(tipo: str | None, concepto: str | None, importe: Decimal | None, fecha: date | None):
    if tipo is not None and tipo not in _TIPOS_DE_DINERO:
        raise MovimientoNoValido("el tipo tiene que ser trabajo o gasto")
    if concepto is not None and not concepto.strip():
        raise MovimientoNoValido("falta el concepto")
    if importe is not None and importe <= 0:
        raise MovimientoNoValido("el importe tiene que ser mayor que cero")
    if fecha is not None and fecha > hoy_local():
        # Un gasto o un cobro de mañana todavía no ha pasado: eso es una cita.
        raise MovimientoNoValido("la fecha no puede ser futura")


def crear_movimiento(
    db: Session,
    user_id: int,
    tipo: str,
    concepto: str,
    importe: Decimal,
    fecha: date | None,
    pendiente: bool,
    origen: str,
) -> Apunte:
    """Un trabajo o un gasto con sus datos ya separados, desde un formulario.

    La caja de texto ("Cambio grifo Ana 120") sigue siendo lo rápido; esto es
    para cuando hace falta otra fecha, o el concepto lleva números que el
    parser tomaría por el importe ("Cambiar 2 grifos").
    """
    _validar(tipo, concepto, importe, fecha)
    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy_local(),
        tipo=tipo,
        concepto=concepto.strip(),
        importe=importe,
        # Un gasto no se queda "pendiente de cobro": eso solo lo es un trabajo.
        pendiente=pendiente and tipo == "trabajo",
        origen=origen,
    )
    db.add(apunte)
    db.commit()
    db.refresh(apunte)
    return apunte


def actualizar_apunte(
    db: Session,
    user_id: int,
    apunte_id: int,
    concepto: str | None = None,
    importe: Decimal | None = None,
    pendiente: bool | None = None,
    fecha: date | None = None,
    tipo: str | None = None,
) -> Apunte:
    """Corrige un apunte ya escrito. Sólo cambia lo que se le pase."""
    apunte = _suyo(db, user_id, apunte_id)
    if apunte.tipo not in _TIPOS_DE_DINERO and (tipo is not None or importe is not None):
        # Una nota no tiene importe ni se convierte en dinero desde aquí.
        raise MovimientoNoValido("una nota no lleva importe")
    _validar(tipo, concepto, importe, fecha)
    if tipo is not None:
        apunte.tipo = tipo
        if tipo == "gasto":
            apunte.pendiente = False
    if concepto is not None:
        apunte.concepto = concepto.strip()
    if importe is not None:
        apunte.importe = importe
    if pendiente is not None:
        apunte.pendiente = pendiente and apunte.tipo == "trabajo"
    if fecha is not None:
        apunte.fecha = fecha
    db.commit()
    db.refresh(apunte)
    return apunte


class FechaNoValida(ValueError):
    """No se ha entendido la fecha, o es del futuro."""


def cambiar_fecha(db: Session, user_id: int, apunte_id: int, texto: str) -> Apunte:
    """Mueve un apunte a otro día: /fecha 34 15/10.

    Para el ticket cuya fecha no se pudo leer y quedó en hoy. Se entiende
    como la fecha de un ticket (del pasado): "15/10" sin año es el último 15
    de octubre. Un apunte no se mueve al futuro.
    """
    fecha, _ = fecha_escrita(texto, hoy_local())
    if fecha is None:
        raise FechaNoValida(f"no entiendo «{texto}» como una fecha pasada")
    return actualizar_apunte(db, user_id, apunte_id, fecha=fecha)


def marcar_cobrado(db: Session, user_id: int, apunte_id: int) -> Apunte:
    apunte = _suyo(db, user_id, apunte_id)
    apunte.pendiente = False
    db.commit()
    db.refresh(apunte)
    return apunte


@dataclass
class ApunteAnotado:
    """El apunte creado y, si el nombre no bastó para decidir, a quién preguntar."""

    apunte: Apunte
    candidatos: list = field(default_factory=list)


def anotar(
    db: Session, user_id: int, texto: str, origen: str, admite_nota: bool = False
) -> ApunteAnotado:
    """Crea el apunte y lo cuelga del cliente nombrado, si no hay duda.

    La regla vive aquí y no en el bot para que la web haga exactamente lo
    mismo: es el motivo por el que existe esta capa.

    Con `admite_nota`, lo que no se entiende como importe se guarda como
    nota en vez de rechazarse: "llamar al fontanero el martes" es algo que
    hay que recordar aunque no lleve dinero, y perderlo por no saber
    interpretarlo es peor que guardarlo tal cual.

    El texto vacío se rechaza siempre: una nota en blanco no es nada.
    """
    mencionados = clientes_mencionados(db, user_id, texto)
    unico = mencionados[0].id if len(mencionados) == 1 else None
    try:
        apunte = crear_apunte(db, user_id, texto, origen, cliente_id=unico)
    except TextoNoInterpretable:
        if not admite_nota or not texto.strip():
            raise
        apunte = crear_nota(db, user_id, texto, origen, cliente_id=unico)
    return ApunteAnotado(
        apunte=apunte,
        candidatos=mencionados if len(mencionados) > 1 else [],
    )
