"""Reglas puras de la conexión con el banco: qué banco, cuánto pedir de
permiso y cómo se lee un movimiento. No llama a nadie ni toca la base.

Los movimientos llegan en el formato de Enable Banking (ISO 20022): importe
en texto, `DBIT` (sale) o `CRDT` (entra), y el concepto repartido entre el
nombre del otro y la "información de remesa". Aquí se deja en lo que la app
entiende: fecha, importe en positivo, si es gasto, y un concepto legible.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

UN_DIA = 86400
# PSD2 no deja más de 180 días; se pide un día menos que el máximo del banco
# porque pedir justo el máximo lo rechazan algunos (cambio de hora de por medio).
_MAXIMO_SEGUNDOS = 180 * UN_DIA


def elegir_banco(lista: list[dict], buscado: str) -> dict | None:
    """El banco que se busca: el nombre exacto, o "Banco <nombre>", o el de
    nombre más corto que lo contenga ("Santander" → "Banco Santander" antes
    que "Santander Consumer Finance")."""
    buscado = buscado.strip().lower()
    por_nombre = {b.get("name", "").lower(): b for b in lista}
    for preferido in (buscado, f"banco {buscado}"):
        if preferido in por_nombre:
            return por_nombre[preferido]
    contienen = [b for b in lista if buscado in b.get("name", "").lower()]
    return min(contienen, key=lambda b: len(b.get("name", "")), default=None)


def hasta_del_permiso(ahora: datetime, maximo_segundos: int | None) -> datetime:
    """Hasta cuándo pedir el permiso: lo máximo que deja el banco, menos un día."""
    maximo = min(maximo_segundos or UN_DIA, _MAXIMO_SEGUNDOS)
    segundos = maximo - UN_DIA if maximo > 2 * UN_DIA else maximo
    return ahora + timedelta(seconds=segundos)


@dataclass(frozen=True)
class MovimientoBanco:
    fecha: date | None
    importe: Decimal
    es_gasto: bool
    concepto: str
    pendiente: bool  # aún sin cargar del todo (status PDNG)


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def _limpio(texto: str) -> str:
    return " ".join((texto or "").split())


def leer_movimiento(m: dict) -> MovimientoBanco | None:
    """Un movimiento de Enable Banking, o None si no trae importe."""
    try:
        importe = Decimal(str((m.get("transaction_amount") or {}).get("amount")))
    except (InvalidOperation, TypeError):
        return None
    if not importe.is_finite():
        return None
    es_gasto = m.get("credit_debit_indicator") == "DBIT" or importe < 0
    otro = (m.get("creditor") if es_gasto else m.get("debtor")) or {}
    remesa = m.get("remittance_information") or []
    if isinstance(remesa, str):
        remesa = [remesa]
    concepto = _limpio(otro.get("name") or "") or _limpio(" ".join(remesa)) or "(sin concepto)"
    return MovimientoBanco(
        fecha=_fecha(m.get("booking_date") or m.get("transaction_date") or m.get("value_date")),
        importe=abs(importe),
        es_gasto=es_gasto,
        concepto=concepto[:120],
        pendiente=m.get("status") == "PDNG",
    )


def final_del_iban(iban: str | None) -> str:
    """Solo las cuatro últimas cifras: para reconocer la cuenta sin enseñarla."""
    limpio = (iban or "").replace(" ", "")
    return f"…{limpio[-4:]}" if limpio else ""
