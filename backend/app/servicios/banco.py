"""Conectar la cuenta del banco, ver qué llega y preguntar por cada pago.

Para no apuntar a mano los pagos con tarjeta, la app lee los movimientos de
la cuenta por PSD2, a través de Enable Banking (`nucleo/banco.py`). Este
servicio conecta, enseña lo que se ve (cuentas, cuánto dura el permiso,
últimos movimientos) y lee lo nuevo cada poco para preguntar por cada pago:
Casa, Negocio, Ya estaba apuntado o Ignorar. Nunca se decide por él: una
cuenta mezcla la compra del súper con el material de una obra.

Cómo va el permiso:
1. `iniciar()` busca el banco, pide un enlace hasta el máximo que deja el
   banco y guarda una conexión "pendiente" con una clave aleatoria.
2. Se confirma en la app del banco, que vuelve a `/banco/vuelta` con esa
   clave y un código. La página de vuelta no lleva token: la clave es lo que
   dice de quién es, sirve una sola vez y caduca en una hora.
3. `completar()` cambia el código por una sesión y la deja "activa"; la que
   hubiera antes de esa persona queda "sustituida".
"""
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.dominio.banco import (
    MovimientoBanco,
    cargado,
    elegir_banco,
    estructura,
    final_del_iban,
    hasta_del_permiso,
    leer_movimiento,
    referencia_de,
    sin_tarjeta,
)
from app.dominio.models import Apunte, ConexionBanco, GastoCasa, MovimientoLeido
from app.nucleo import banco as enable
from app.nucleo.config import BANCO_NOMBRE, BANCO_PAIS, URL_API
from app.nucleo.tiempo import hoy_local
from app.servicios import casa
from app.servicios.apuntes import crear_movimiento, marcar_cobrado, obtener_apunte

# Lo que tarda uno en confirmar en la app del banco, con margen.
_CADUCA_LA_VUELTA = timedelta(hours=1)
DIAS_DE_MUESTRA = 30


class ConexionNoValida(ValueError):
    """La vuelta del banco no corresponde a ninguna conexión pendiente."""


@dataclass
class CuentaVista:
    nombre: str
    tipo: str
    final_iban: str
    movimientos: int


@dataclass
class ResumenBanco:
    banco: str
    valido_hasta: datetime | None
    cuentas: list[CuentaVista] = field(default_factory=list)
    ultimos: list[MovimientoBanco] = field(default_factory=list)
    sin_fecha: int = 0

    @property
    def dias_de_permiso(self) -> int | None:
        if self.valido_hasta is None:
            return None
        return max(0, (self.valido_hasta - datetime.now(timezone.utc)).days)


def url_de_vuelta() -> str:
    return f"{URL_API}/banco/vuelta"


def _utc(momento: datetime | None) -> datetime | None:
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


async def iniciar(db: Session, user_id: int) -> str:
    """El enlace para dar permiso en el banco. Deja una conexión pendiente."""
    if not URL_API:
        raise enable.BancoNoDisponible("falta URL_API (la dirección pública de la API) en el entorno")
    banco = elegir_banco(await enable.bancos(BANCO_PAIS), BANCO_NOMBRE)
    if banco is None:
        raise enable.ErrorDeBanco(f"no encuentro «{BANCO_NOMBRE}» entre los bancos de {BANCO_PAIS}")
    hasta = hasta_del_permiso(datetime.now(timezone.utc), banco.get("maximum_consent_validity"))
    clave = secrets.token_urlsafe(24)
    url = await enable.autorizar(banco["name"], BANCO_PAIS, hasta, clave, url_de_vuelta())
    db.add(
        ConexionBanco(
            user_id=user_id, banco=banco["name"], estado="pendiente", clave_vuelta=clave, valido_hasta=hasta
        )
    )
    db.commit()
    return url


def _pendiente(db: Session, clave: str) -> ConexionBanco:
    conexion = (
        db.query(ConexionBanco)
        .filter(ConexionBanco.clave_vuelta == clave, ConexionBanco.estado == "pendiente")
        .first()
        if clave
        else None
    )
    if conexion is None:
        raise ConexionNoValida("este enlace ya se usó o no es de aquí: pide otro con /banco")
    creado = _utc(conexion.creado)
    if creado and datetime.now(timezone.utc) - creado > _CADUCA_LA_VUELTA:
        raise ConexionNoValida("el enlace ha caducado: pide otro con /banco")
    return conexion


async def completar(db: Session, clave: str, codigo: str) -> ResumenBanco:
    """La vuelta del banco: guarda la sesión y devuelve lo que se ve."""
    conexion = _pendiente(db, clave)
    sesion = await enable.crear_sesion(codigo)
    cuentas = [
        {
            "uid": c["uid"],
            "nombre": c.get("name") or c.get("product") or "Cuenta",
            "tipo": c.get("cash_account_type") or "",
            "final_iban": final_del_iban((c.get("account_id") or {}).get("iban")),
        }
        for c in sesion.get("accounts") or []
        if c.get("uid")
    ]
    hasta = (sesion.get("access") or {}).get("valid_until")
    if hasta:
        try:
            conexion.valido_hasta = datetime.fromisoformat(hasta.replace("Z", "+00:00"))
        except ValueError:
            pass
    for vieja in db.query(ConexionBanco).filter(
        ConexionBanco.user_id == conexion.user_id, ConexionBanco.estado == "activa"
    ):
        vieja.estado = "sustituida"
    conexion.estado = "activa"
    conexion.sesion = sesion.get("session_id")
    conexion.clave_vuelta = None  # una sola vez
    conexion.cuentas = json.dumps(cuentas, ensure_ascii=False)
    db.commit()
    return await _resumen(conexion)


def activa(db: Session, user_id: int) -> ConexionBanco | None:
    return (
        db.query(ConexionBanco)
        .filter(ConexionBanco.user_id == user_id, ConexionBanco.estado == "activa")
        .order_by(ConexionBanco.id.desc())
        .first()
    )


async def _resumen(conexion: ConexionBanco) -> ResumenBanco:
    resumen = ResumenBanco(banco=conexion.banco, valido_hasta=_utc(conexion.valido_hasta))
    desde = hoy_local() - timedelta(days=DIAS_DE_MUESTRA)
    todos: list[MovimientoBanco] = []
    for cuenta in json.loads(conexion.cuentas or "[]"):
        leidos = [m for m in map(leer_movimiento, await enable.movimientos(cuenta["uid"], desde)) if m]
        todos += leidos
        resumen.cuentas.append(
            CuentaVista(cuenta["nombre"], cuenta["tipo"], cuenta["final_iban"], len(leidos))
        )
    # Los que no traen fecha van al final, pero se enseñan: un hueco se ve.
    resumen.ultimos = sorted(todos, key=lambda m: (m.fecha is not None, m.fecha or hoy_local()), reverse=True)[:10]
    resumen.sin_fecha = sum(1 for m in todos if m.fecha is None)
    return resumen


async def ver(db: Session, user_id: int) -> ResumenBanco | None:
    """Lo que se ve ahora de la cuenta conectada; None si no hay ninguna."""
    conexion = activa(db, user_id)
    if conexion is None:
        return None
    return await _resumen(conexion)


async def muestra(db: Session, user_id: int, cuantos: int = 5) -> list[dict]:
    """La forma de los últimos movimientos que manda el banco (`estructura`).

    Para ver dónde pone cada banco la fecha, el comercio o el importe sin
    enseñar ni conceptos ni importes. Vacía si no hay conexión.
    """
    conexion = activa(db, user_id)
    if conexion is None:
        return []
    desde = hoy_local() - timedelta(days=DIAS_DE_MUESTRA)
    formas: list[dict] = []
    for cuenta in json.loads(conexion.cuentas or "[]"):
        formas += [estructura(m) for m in (await enable.movimientos(cuenta["uid"], desde))[:cuantos]]
    return formas[:cuantos]



# --- Lo nuevo: leerlo y preguntar por cada pago --------------------------------

# La primera vez se mira un mes (y se marca como ya visto); después, una
# semana hacia atrás, porque los pagos con tarjeta tardan días en cargarse.
_DIAS_PRIMERA_LECTURA = DIAS_DE_MUESTRA
_DIAS_DE_SOLAPE = 7
# Margen para reconocer algo ya apuntado: el banco carga el pago días después.
_DIAS_DE_MARGEN = 3
# Con cuánta antelación se avisa de que el permiso caduca.
_AVISO_CADUCIDAD = timedelta(days=7)

DECIDIDOS = {"casa", "negocio", "cobro", "ya_estaba", "ignorado"}


def activas(db: Session) -> list[ConexionBanco]:
    return db.query(ConexionBanco).filter(ConexionBanco.estado == "activa").all()


def caducada(conexion: ConexionBanco) -> bool:
    hasta = _utc(conexion.valido_hasta)
    return hasta is not None and hasta <= datetime.now(timezone.utc)


async def leer_nuevos(db: Session, conexion: ConexionBanco) -> list[MovimientoLeido]:
    """Guarda lo que haya llegado desde la última vez. Devuelve lo que hay que preguntar.

    La primera lectura solo marca lo que ya había ("antiguo"): al conectar,
    preguntar por un mes entero de golpe sería un muro de mensajes. Los
    pendientes no se guardan: vuelven cargados, a veces con otro importe.
    """
    if caducada(conexion):
        return []
    primera = conexion.leida is None
    desde = hoy_local() - timedelta(days=_DIAS_PRIMERA_LECTURA if primera else _DIAS_DE_SOLAPE)
    nuevos: list[MovimientoLeido] = []
    for cuenta in json.loads(conexion.cuentas or "[]"):
        vistos = {
            fila[0]
            for fila in db.query(MovimientoLeido.referencia).filter(MovimientoLeido.cuenta == cuenta["uid"])
        }
        for crudo in await enable.movimientos(cuenta["uid"], desde):
            if not cargado(crudo):
                continue
            referencia = referencia_de(crudo)
            leido = leer_movimiento(crudo)
            if referencia in vistos or leido is None or leido.importe == 0:
                continue
            vistos.add(referencia)
            movimiento = MovimientoLeido(
                conexion_id=conexion.id,
                user_id=conexion.user_id,
                cuenta=cuenta["uid"],
                referencia=referencia,
                fecha=leido.fecha,
                importe=leido.importe,
                es_gasto=leido.es_gasto,
                concepto=leido.concepto,
                texto=sin_tarjeta(" ".join(crudo.get("remittance_information") or []))[:300] or None,
                estado="antiguo" if primera else "nuevo",
            )
            db.add(movimiento)
            if not primera:
                nuevos.append(movimiento)
    conexion.leida = datetime.now(timezone.utc)
    db.commit()
    return nuevos


def por_preguntar(db: Session, user_id: int | None = None) -> list[MovimientoLeido]:
    consulta = db.query(MovimientoLeido).filter(MovimientoLeido.estado == "nuevo")
    if user_id is not None:
        consulta = consulta.filter(MovimientoLeido.user_id == user_id)
    return consulta.order_by(MovimientoLeido.fecha, MovimientoLeido.id).all()


def marcar_preguntado(db: Session, movimiento: MovimientoLeido) -> None:
    if movimiento.estado == "nuevo":
        movimiento.estado = "preguntado"
        db.commit()


@dataclass
class Pregunta:
    movimiento: MovimientoLeido
    # Algo ya apuntado que parece este mismo pago (el ticket escaneado, etc.).
    parecido: str | None = None
    # Si entra dinero: trabajos pendientes de cobro por ese mismo importe.
    cobros: list[Apunte] = field(default_factory=list)


def _alrededor(fecha):
    dia = fecha or hoy_local()
    return dia - timedelta(days=_DIAS_DE_MARGEN), dia + timedelta(days=_DIAS_DE_MARGEN)


def pregunta_de(db: Session, movimiento: MovimientoLeido) -> Pregunta:
    """Lo que hay que enseñar con la pregunta: si ya parece apuntado y, si
    entra dinero, qué cobros pendientes podrían ser."""
    desde, hasta = _alrededor(movimiento.fecha)
    pregunta = Pregunta(movimiento)
    tipo = "gasto" if movimiento.es_gasto else "trabajo"
    apunte = (
        db.query(Apunte)
        .filter(
            Apunte.user_id == movimiento.user_id,
            Apunte.tipo == tipo,
            Apunte.importe == movimiento.importe,
            Apunte.fecha >= desde,
            Apunte.fecha <= hasta,
            Apunte.origen != "banco",
        )
        .first()
    )
    if apunte is not None:
        pregunta.parecido = f"«{apunte.concepto}» en el negocio, {apunte.fecha:%d/%m}"
    elif movimiento.es_gasto:
        miembro = casa.miembro_de(db, movimiento.user_id)
        gasto = None
        if miembro is not None:
            gasto = (
                db.query(GastoCasa)
                .filter(
                    GastoCasa.hogar_id == miembro.hogar_id,
                    GastoCasa.importe == movimiento.importe,
                    GastoCasa.fecha >= desde,
                    GastoCasa.fecha <= hasta,
                    GastoCasa.origen != "banco",
                )
                .first()
            )
        if gasto is not None:
            pregunta.parecido = f"«{gasto.concepto}» en Casa, {gasto.fecha:%d/%m}"
    if not movimiento.es_gasto:
        pregunta.cobros = (
            db.query(Apunte)
            .filter(
                Apunte.user_id == movimiento.user_id,
                Apunte.tipo == "trabajo",
                Apunte.pendiente.is_(True),
                Apunte.importe == movimiento.importe,
            )
            .order_by(Apunte.fecha.desc())
            .limit(3)
            .all()
        )
    return pregunta


class MovimientoNoEncontrado(LookupError):
    """No existe ese movimiento para esa persona."""


@dataclass
class Decision:
    movimiento: MovimientoLeido
    apunte: Apunte | None = None
    gasto: GastoCasa | None = None
    # Ya se había decidido antes (dos toques, o desde otro sitio): no se repite.
    ya_decidido: bool = False


def decidir(
    db: Session, user_id: int, movimiento_id: int, accion: str, cobro_id: int | None = None
) -> Decision:
    """Lo que se elige en la pregunta. Una sola vez por movimiento.

    - "casa": gasto de Casa, pagado con tarjeta, con su categoría adivinada.
    - "negocio": gasto (o cobro, si entró dinero) del negocio; desde ahí se
      mete en un trabajo con sus botones de siempre.
    - "cobro": el trabajo pendiente `cobro_id` queda cobrado.
    - "ya_estaba" o "ignorado": no se apunta nada.
    """
    movimiento = (
        db.query(MovimientoLeido)
        .filter(MovimientoLeido.id == movimiento_id, MovimientoLeido.user_id == user_id)
        .first()
    )
    if movimiento is None:
        raise MovimientoNoEncontrado("ese movimiento ya no está")
    if movimiento.estado in DECIDIDOS:
        decision = Decision(movimiento, ya_decidido=True)
        if movimiento.apunte_id:
            decision.apunte = db.get(Apunte, movimiento.apunte_id)
        if movimiento.gasto_casa_id:
            decision.gasto = db.get(GastoCasa, movimiento.gasto_casa_id)
        return decision

    decision = Decision(movimiento)
    fecha = movimiento.fecha or hoy_local()
    if accion == "casa":
        if not movimiento.es_gasto:
            raise ValueError("en Casa solo se apuntan gastos")
        decision.gasto = casa.crear_gasto(
            db, user_id, movimiento.concepto, movimiento.importe, fecha=fecha, origen="banco", efectivo=False
        )
        movimiento.gasto_casa_id = decision.gasto.id
        movimiento.estado = "casa"
    elif accion == "negocio":
        tipo = "gasto" if movimiento.es_gasto else "trabajo"
        decision.apunte = crear_movimiento(
            db, user_id, tipo, movimiento.concepto, movimiento.importe, fecha, False, "banco"
        )
        movimiento.apunte_id = decision.apunte.id
        movimiento.estado = "negocio"
    elif accion == "cobro":
        if movimiento.es_gasto or cobro_id is None:
            raise ValueError("solo un ingreso puede ser el cobro de un trabajo")
        obtener_apunte(db, user_id, cobro_id)
        decision.apunte = marcar_cobrado(db, user_id, cobro_id)
        movimiento.apunte_id = cobro_id
        movimiento.estado = "cobro"
    elif accion in ("ya_estaba", "ignorado"):
        movimiento.estado = accion
    else:
        raise ValueError(f"acción desconocida: {accion}")
    db.commit()
    return decision


def avisar_de_caducidad(db: Session) -> list[ConexionBanco]:
    """Las conexiones a las que hay que avisar de que el permiso caduca.

    Una vez por conexión, siete días antes (o en cuanto se vea, si ya está
    más cerca): queda apuntado en `aviso_caducidad`.
    """
    ahora = datetime.now(timezone.utc)
    avisar = []
    for conexion in activas(db):
        hasta = _utc(conexion.valido_hasta)
        if hasta is None or conexion.aviso_caducidad is not None:
            continue
        if hasta - ahora <= _AVISO_CADUCIDAD:
            conexion.aviso_caducidad = hoy_local()
            avisar.append(conexion)
    db.commit()
    return avisar
