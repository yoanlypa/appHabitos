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
from app.dominio.parsing import TextoNoInterpretable, interpretar_con_fecha
from app.dominio.tickets import fecha_escrita
from app.nucleo.tiempo import hoy_local
from app.servicios.clientes import clientes_mencionados


class ApunteNoEncontrado(LookupError):
    """No existe un apunte con ese id para ese usuario."""


def crear_apunte(
    db: Session, user_id: int, texto: str, origen: str, cliente_id: int | None = None
) -> Apunte:
    # El día puede ir delante ("ayer -45 gasolina"); si no, es de hoy.
    hoy = hoy_local()
    interpretado, fecha = interpretar_con_fecha(texto, hoy)
    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy,
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


def obtener_apunte(db: Session, user_id: int, apunte_id: int) -> Apunte:
    """Un apunte por su número, solo si es de quien lo pide."""
    return _suyo(db, user_id, apunte_id)


def borrar_apunte(db: Session, user_id: int, apunte_id: int) -> Apunte:
    """Borra un apunte. Se devuelve el borrado para poder decir qué se fue.

    Hace falta de verdad: se apunta con una mano en mitad de un trabajo y se
    escribe 1200 donde iba 120. Sin esto, el error se queda en las cuentas
    para siempre.
    """
    apunte = _suyo(db, user_id, apunte_id)
    _soltar_gastos(db, apunte)
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


_SIN_TOCAR = object()  # None es un valor válido: "este gasto ya no es de ningún trabajo"


def _trabajo_suyo(db: Session, user_id: int, trabajo_id: int, salvo: int | None = None) -> Apunte:
    """El trabajo del que se quiere colgar un gasto: tiene que existir, ser suyo y ser un trabajo."""
    trabajo = (
        db.query(Apunte)
        .filter(Apunte.id == trabajo_id, Apunte.user_id == user_id, Apunte.tipo == "trabajo")
        .first()
    )
    if trabajo is None or trabajo.id == salvo:
        raise MovimientoNoValido("ese trabajo no existe")
    return trabajo


def trabajo_de_gasto(db: Session, user_id: int, trabajo_id: int) -> Apunte:
    """Para quien cuelga un gasto de un trabajo desde otro servicio (los tickets)."""
    return _trabajo_suyo(db, user_id, trabajo_id)


def _soltar_gastos(db: Session, trabajo: Apunte) -> None:
    """Deja sueltos los gastos de un trabajo que va a dejar de serlo (se borra o pasa a gasto).

    Cada gasto conserva lo que valía para la gestoría: si el trabajo estaba
    facturado, sus gastos quedan marcados a mano. Borrar un trabajo por
    error no puede sacar sus gastos de lo que se manda sin que nadie lo vea.
    """
    for gasto in list(trabajo.gastos):
        gasto.para_gestoria = bool(trabajo.facturado)
        gasto.trabajo_id = None


def _ordenar_marcas(db: Session, apunte: Apunte) -> None:
    """Cada marca solo vale para su tipo; lo que no aplica se limpia.

    Un gasto no está "facturado" y un trabajo no cuelga de otro trabajo. Y un
    trabajo con una factura emitida colgada está facturado se diga lo que se
    diga: el papel manda.
    """
    if apunte.tipo != "gasto":
        apunte.trabajo_id = None
        apunte.para_gestoria = False
    if apunte.tipo != "trabajo":
        # Antes de quitarle la marca: los gastos se sueltan con lo que valían.
        if apunte.id is not None:
            _soltar_gastos(db, apunte)
        apunte.facturado = False
    elif apunte.factura_emitida:
        apunte.facturado = True
    if apunte.trabajo_id is not None:
        # Sigue a su trabajo: la marca a mano ya no pinta nada, y si se
        # quedara puesta reaparecería sola el día que se desasigne.
        apunte.para_gestoria = False


def crear_movimiento(
    db: Session,
    user_id: int,
    tipo: str,
    concepto: str,
    importe: Decimal,
    fecha: date | None,
    pendiente: bool,
    origen: str,
    trabajo_id: int | None = None,
    facturado: bool = False,
    para_gestoria: bool = False,
) -> Apunte:
    """Un trabajo o un gasto con sus datos ya separados, desde un formulario.

    La caja de texto ("Cambio grifo Ana 120") sigue siendo lo rápido; esto es
    para cuando hace falta otra fecha, o el concepto lleva números que el
    parser tomaría por el importe ("Cambiar 2 grifos"). Y para decir de qué
    trabajo es un gasto, o si un trabajo lo factura Yoa.
    """
    _validar(tipo, concepto, importe, fecha)
    if trabajo_id is not None and tipo == "gasto":
        _trabajo_suyo(db, user_id, trabajo_id)
    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy_local(),
        tipo=tipo,
        concepto=concepto.strip(),
        importe=importe,
        # Un gasto no se queda "pendiente de cobro": eso solo lo es un trabajo.
        pendiente=pendiente and tipo == "trabajo",
        origen=origen,
        trabajo_id=trabajo_id,
        facturado=facturado,
        para_gestoria=para_gestoria,
    )
    _ordenar_marcas(db, apunte)
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
    trabajo_id=_SIN_TOCAR,
    facturado: bool | None = None,
    para_gestoria: bool | None = None,
) -> Apunte:
    """Corrige un apunte ya escrito. Sólo cambia lo que se le pase.

    `trabajo_id` usa un centinela en vez de None, porque "no toques de qué
    trabajo es" y "ya no es de ninguno" son cosas distintas.
    """
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
    if trabajo_id is not _SIN_TOCAR:
        if trabajo_id is not None and apunte.tipo == "gasto":
            _trabajo_suyo(db, user_id, trabajo_id, salvo=apunte.id)
        apunte.trabajo_id = trabajo_id
    if facturado is not None:
        apunte.facturado = facturado
    if para_gestoria is not None:
        apunte.para_gestoria = para_gestoria
    _ordenar_marcas(db, apunte)
    db.commit()
    db.refresh(apunte)
    return apunte


def trabajos_para_elegir(db: Session, user_id: int, limite: int = 200) -> list[Apunte]:
    """Los trabajos entre los que elegir al decir de cuál es un gasto.

    El más reciente primero: un gasto casi siempre es de un trabajo de estos
    días. Con tope, porque esto alimenta un desplegable y no un listado.
    """
    return (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.tipo == "trabajo")
        .order_by(Apunte.fecha.desc(), Apunte.id.desc())
        .limit(limite)
        .all()
    )


@dataclass
class FichaTrabajo:
    """Un trabajo con lo que ha costado hacerlo."""

    trabajo: Apunte
    gastos: list[Apunte]
    total_gastos: Decimal

    @property
    def beneficio(self) -> Decimal:
        return self.trabajo.importe - self.total_gastos


def ficha_trabajo(db: Session, user_id: int, apunte_id: int) -> FichaTrabajo:
    """El trabajo, sus gastos y lo que queda. La suma se hace aquí, no en la web."""
    trabajo = _suyo(db, user_id, apunte_id)
    if trabajo.tipo != "trabajo":
        raise ApunteNoEncontrado(f"el apunte {apunte_id} no es un trabajo")
    gastos = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.trabajo_id == trabajo.id, Apunte.tipo == "gasto")
        .order_by(Apunte.fecha, Apunte.id)
        .all()
    )
    return FichaTrabajo(
        trabajo=trabajo,
        gastos=gastos,
        total_gastos=sum((g.importe for g in gastos), Decimal("0")),
    )


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
