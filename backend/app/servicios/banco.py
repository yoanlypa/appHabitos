"""Conectar la cuenta del banco y ver qué llega. Primer paso: la prueba.

Para no apuntar a mano los pagos con tarjeta, la app lee los movimientos de
la cuenta por PSD2, a través de Enable Banking (`nucleo/banco.py`). Este
primer paso solo conecta y enseña lo que se ve: cuentas, cuánto dura el
permiso y los últimos movimientos. Preguntar por cada pago (Casa, Negocio o
Ignorar) vendrá cuando se sepa qué trae de verdad el banco.

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

from app.dominio.banco import MovimientoBanco, elegir_banco, final_del_iban, hasta_del_permiso, leer_movimiento
from app.dominio.models import ConexionBanco
from app.nucleo import banco as enable
from app.nucleo.config import BANCO_NOMBRE, BANCO_PAIS, URL_API
from app.nucleo.tiempo import hoy_local

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
    resumen.ultimos = sorted(todos, key=lambda m: m.fecha or hoy_local(), reverse=True)[:10]
    return resumen


async def ver(db: Session, user_id: int) -> ResumenBanco | None:
    """Lo que se ve ahora de la cuenta conectada; None si no hay ninguna."""
    conexion = activa(db, user_id)
    if conexion is None:
        return None
    return await _resumen(conexion)
