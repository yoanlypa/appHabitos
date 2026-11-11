"""Meter varios movimientos de una vez, enseñándolos antes y sin repetir.

Los movimientos llegan ya leídos (`dominio/importacion.py`): de un mensaje
con varias líneas, de un CSV o un Excel, o de una captura con varios pagos.
Aquí se decide cuáles entran.

Va en dos pasos, como restaurar una copia: `planificar()` para enseñar lo
que entraría y `importar()` cuando se dice que sí. Lo importado es dinero,
y once gastos mal leídos se arreglan peor que uno.

Cuándo un movimiento "ya está": mismo día, mismo tipo y mismo importe. El
concepto NO entra, al revés que en `restauracion.py`, y es adrede: dos
capturas del mismo historial se solapan, y el modelo puede llamar a la misma
fila "Parking Sector 2" en una y "Estacionamiento Sector 2" en la otra; con
el concepto en la comparación entraría dos veces. Se cuenta, no se busca:
si la lista trae dos parkings de 2,75 del mismo día y en la base hay uno,
falta uno.

El precio es el caso contrario —un gasto distinto del mismo día y por el
mismo importe se toma por repetido— y por eso lo apartado se enseña y se
puede meter igualmente (`todo=True`). Nunca se descarta en silencio.
"""
from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.importacion import Movimiento, de_lectura
from app.dominio.models import Apunte
from app.nucleo.lectura_tickets import leer_movimientos
from app.nucleo.tiempo import hoy_local
from app.servicios.clientes import clientes_mencionados

_CENTIMO = Decimal("0.01")


@dataclass
class PlanDeImportacion:
    nuevos: list[Movimiento] = field(default_factory=list)
    # Los que parecen estar ya (mismo día, tipo e importe). Se enseñan.
    repetidos: list[Movimiento] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.nuevos) + len(self.repetidos)


def con_tipo(movimientos: list[Movimiento], tipo: str) -> list[Movimiento]:
    """Pone el tipo a los que no lo traían, cuando ya se ha preguntado."""
    return [m if m.tipo is not None else replace(m, tipo=tipo) for m in movimientos]


def falta_el_tipo(movimientos: list[Movimiento]) -> bool:
    return any(m.tipo is None for m in movimientos)


def _clave(fecha, tipo, importe) -> tuple:
    return (fecha, tipo, Decimal(importe).quantize(_CENTIMO))


def planificar(db: Session, user_id: int, movimientos: list[Movimiento]) -> PlanDeImportacion:
    """Qué entraría si se importa ahora. No escribe nada."""
    if not movimientos:
        return PlanDeImportacion()
    desde = min(m.fecha for m in movimientos)
    hasta = max(m.fecha for m in movimientos)
    en_la_base = Counter(
        _clave(a.fecha, a.tipo, a.importe)
        for a in db.query(Apunte).filter(
            Apunte.user_id == user_id,
            Apunte.fecha >= desde,
            Apunte.fecha <= hasta,
            Apunte.tipo != "nota",
        )
    )
    plan = PlanDeImportacion()
    for movimiento in movimientos:
        clave = _clave(movimiento.fecha, movimiento.tipo, movimiento.importe)
        if en_la_base[clave] > 0:
            en_la_base[clave] -= 1
            plan.repetidos.append(movimiento)
        else:
            plan.nuevos.append(movimiento)
    return plan


def importar(
    db: Session, user_id: int, movimientos: list[Movimiento], origen: str, todo: bool = False
) -> list[Apunte]:
    """Mete los que faltan (o todos, con `todo`). Devuelve lo que ha entrado.

    Se vuelve a planificar aquí en vez de fiarse de la vista previa: entre
    enseñarla y confirmar puede haberse importado la otra captura del mismo
    historial, y lo que se solapa no puede acabar dos veces.

    El cliente se cuelga con la regla de siempre: si el concepto nombra a
    uno solo, de él; si hay dos Anas, de ninguno. Aquí no se pregunta fila a
    fila: se arregla después en la web.
    """
    if falta_el_tipo(movimientos):
        raise ValueError("hay movimientos sin tipo: hay que decir si son gastos o cobros")
    hoy = hoy_local()
    if any(m.fecha > hoy for m in movimientos):
        raise ValueError("hay movimientos con fecha futura")

    elegidos = movimientos if todo else planificar(db, user_id, movimientos).nuevos
    apuntes = []
    for movimiento in elegidos:
        mencionados = clientes_mencionados(db, user_id, movimiento.concepto)
        apunte = Apunte(
            user_id=user_id,
            fecha=movimiento.fecha,
            tipo=movimiento.tipo,
            concepto=movimiento.concepto,
            importe=movimiento.importe,
            pendiente=movimiento.pendiente and movimiento.tipo == "trabajo",
            origen=origen,
            cliente_id=mencionados[0].id if len(mencionados) == 1 else None,
        )
        db.add(apunte)
        apuntes.append(apunte)
    db.commit()
    for apunte in apuntes:
        db.refresh(apunte)
    return apuntes


def borrar_importados(db: Session, user_id: int, ids: list[int]) -> int:
    """Deshace una importación recién hecha. Devuelve cuántos se han ido.

    Solo lo que sigue siendo suyo y sigue ahí: si entre medias se borró uno
    a mano, no es un error.
    """
    if not ids:
        return 0
    apuntes = (
        db.query(Apunte)
        .filter(Apunte.user_id == user_id, Apunte.id.in_(ids), Apunte.tipo != "nota")
        .all()
    )
    borrados = 0
    for apunte in apuntes:
        # Lo importado no trae ticket ni gastos colgados; si desde entonces se
        # le ha colgado algo, ya no es "lo recién importado": se deja.
        if apunte.factura is not None or apunte.gastos:
            continue
        db.delete(apunte)
        borrados += 1
    db.commit()
    return borrados


async def leer_captura(imagen: bytes, mime: str) -> list[Movimiento]:
    """Los movimientos de una captura con varios pagos, ya filtrados."""
    return de_lectura(await leer_movimientos(imagen, mime), hoy_local())
