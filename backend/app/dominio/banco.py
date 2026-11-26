"""Reglas puras de la conexión con el banco: qué banco, cuánto pedir de
permiso y cómo se lee un movimiento. No llama a nadie ni toca la base.

Los movimientos llegan en el formato de Enable Banking (ISO 20022): importe
en texto, `DBIT` (sale) o `CRDT` (entra), y el concepto repartido entre el
nombre del otro y la "información de remesa". Aquí se deja en lo que la app
entiende: fecha, importe en positivo, si es gasto, y un concepto legible.
"""
import hashlib
import re
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


_FORMATOS_DE_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d", "%d.%m.%Y")
# Dónde puede venir el día de un movimiento, por orden de preferencia: el
# del apunte en la cuenta, el de la operación, el valor. Santander (vía
# Redsys) no siempre rellena el primero.
_CAMPOS_DE_FECHA = ("booking_date", "transaction_date", "value_date", "booking_date_time", "value_date_time")


def _fecha(valor) -> date | None:
    """Un día, venga en ISO, con hora pegada o a la española."""
    if not valor:
        return None
    texto = str(valor).strip()
    for formato in _FORMATOS_DE_FECHA:
        for trozo in (texto[:10], texto[:8], texto):
            try:
                return datetime.strptime(trozo, formato).date()
            except ValueError:
                continue
    return None


def fecha_de(m: dict) -> date | None:
    for campo in _CAMPOS_DE_FECHA:
        dia = _fecha(m.get(campo))
        if dia:
            return dia
    # Último recurso: cualquier campo que se llame "...date..." y sea una fecha.
    for campo, valor in m.items():
        if "date" in campo.lower():
            dia = _fecha(valor)
            if dia:
                return dia
    return None


def estructura(m: dict) -> dict:
    """Qué campos trae un movimiento, sin sus valores (salvo las fechas).

    Para ver dónde pone cada banco cada cosa sin enseñar conceptos ni
    importes: solo los nombres de los campos con algo dentro, y lo que traen
    los que parecen fechas, que no dicen nada de nadie.
    """
    return {
        campo: (valor if "date" in campo.lower() else type(valor).__name__)
        for campo, valor in m.items()
        if valor not in (None, "", [], {})
    }


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
    concepto = _limpio(otro.get("name") or "") or concepto_de_banco(" ".join(remesa))
    return MovimientoBanco(
        fecha=fecha_de(m),
        importe=abs(importe),
        es_gasto=es_gasto,
        concepto=concepto[:120],
        pendiente=m.get("status") == "PDNG",
    )


def final_del_iban(iban: str | None) -> str:
    """Solo las cuatro últimas cifras: para reconocer la cuenta sin enseñarla."""
    limpio = (iban or "").replace(" ", "")
    return f"…{limpio[-4:]}" if limpio else ""


# --- Movimientos nuevos: de quién son y cómo se llaman -----------------------


def referencia_de(m: dict) -> str:
    """Lo que identifica un movimiento para no preguntar dos veces por él.

    Santander manda `entry_reference`, único por movimiento. Si un banco no
    lo manda, se usa una huella con lo que no cambia (día, importe, sentido
    y texto).
    """
    for campo in ("entry_reference", "transaction_id", "reference_number"):
        valor = m.get(campo)
        if valor:
            return str(valor)[:120]
    leido = leer_movimiento(m)
    texto = " ".join(m.get("remittance_information") or [])
    huella = f"{fecha_de(m)}|{leido.importe if leido else ''}|{m.get('credit_debit_indicator')}|{texto}"
    return "h:" + hashlib.sha1(huella.encode("utf-8")).hexdigest()


def cargado(m: dict) -> bool:
    """Ya cargado en la cuenta. Los pendientes (PDNG) pueden cambiar de importe
    o desaparecer, y suelen volver con otra referencia: no se pregunta por ellos."""
    return (m.get("status") or "BOOK") == "BOOK"


# El texto de Santander lleva la tienda entre el verbo y la tarjeta:
# "COMPRA EN MERCADONA, CON LA TARJETA : 5489XXXXXXXX1234 EL 2026-11-24".
_DELANTE = re.compile(
    r"^\s*(?:compra\s+internet\s+en|compra\s+en|compra|pago\s+movil\s+en|pago\s+m[oó]vil\s+en|"
    r"pago\s+en|pago|transferencia\s+inmediata\s+de|transferencia\s+a\s+favor\s+de|"
    r"transferencia\s+de|transferencia|bizum\s+de|bizum\s+a\s+favor\s+de|bizum|recibo|"
    r"devoluci[oó]n\s+compra\s+en|devoluci[oó]n)\b[\s:,.-]*",
    re.IGNORECASE,
)
_DETRAS = re.compile(
    r"(?:,?\s*con\s+la\s+tarjeta.*|,?\s*tarj(?:eta)?\.?\s*:?.*|,?\s*el\s+\d{4}-\d{2}-\d{2}.*|"
    r",?\s*n[ºo°]\s*recibo.*|,?\s*comisi[oó]n\s+[\d,.]+.*)$",
    re.IGNORECASE,
)
_TARJETA = re.compile(r"[\dXx\*]{6,}")
# La tarjeta delante de la tienda: "COMPRA TARJ. 5402XXXXXXXX1234 REPSOL".
_TARJETA_DELANTE = re.compile(r"^tarj(?:eta)?\.?\s*:?\s*[\dXx\*]{6,}\s*", re.IGNORECASE)


def sin_tarjeta(texto: str) -> str:
    """El texto del banco sin números de tarjeta, para guardarlo."""
    return _limpio(_TARJETA.sub("…", texto or ""))


def concepto_de_banco(texto: str) -> str:
    """La tienda o la persona, sin el ruido del banco.

    "COMPRA EN MERCADONA, CON LA TARJETA : 5489XXXXXXXX1234" → "Mercadona".
    "Transferencia De Ana Ruiz, Concepto Reforma Baño" → "Ana Ruiz · Reforma Baño".
    Si después de limpiar no queda nada, se devuelve el texto tal cual: es
    mejor un concepto feo que uno inventado.
    """
    original = _limpio(texto)
    resto = _TARJETA_DELANTE.sub("", _DELANTE.sub("", original, count=1))
    resto = _DETRAS.sub("", resto)
    persona, _, concepto = resto.partition(", concepto")
    if not concepto:
        persona, _, concepto = resto.partition(", Concepto")
    resto = f"{persona.strip(' ,.')} · {concepto.strip(' ,.')}" if concepto.strip(" ,.") else persona
    resto = _limpio(_TARJETA.sub("", resto)).strip(" ,.:-·")
    if not resto:
        return original[:120] or "(sin concepto)"
    if resto.isupper():
        resto = resto.title()
    return resto[:120]
