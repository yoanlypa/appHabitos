"""Interpreta texto libre (del bot o de la web) como un apunte.

Sin dependencias de FastAPI ni de Telegram para poder probarlo con casos
sueltos. Formatos reconocidos:
  "Cambio de grifo Ana 120"      -> trabajo cobrado, 120.00 EUR
  "pendiente Reforma baño 980"   -> trabajo sin cobrar, 980.00 EUR
  "-45 gasolina"                 -> gasto, 45.00 EUR
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_NUMERO = r"\d+(?:[.,]\d{1,2})?"

_RE_GASTO = re.compile(rf"^-({_NUMERO})\s+(.+)$")
_RE_PENDIENTE = re.compile(rf"^pendiente\s+(.+?)\s+({_NUMERO})$", re.IGNORECASE)
_RE_TRABAJO = re.compile(rf"^(.+?)\s+({_NUMERO})$")


class TextoNoInterpretable(ValueError):
    """El texto no tiene la forma esperada para crear un apunte."""


@dataclass
class ApunteInterpretado:
    tipo: str  # "trabajo" | "gasto"
    concepto: str
    importe: Decimal
    pendiente: bool = False


def _a_decimal(texto_numero: str) -> Decimal:
    try:
        return Decimal(texto_numero.replace(",", "."))
    except InvalidOperation as exc:
        raise TextoNoInterpretable(f"'{texto_numero}' no es un importe válido") from exc


def interpretar_texto(texto: str) -> ApunteInterpretado:
    texto = texto.strip()
    if not texto:
        raise TextoNoInterpretable("texto vacío")

    m = _RE_GASTO.match(texto)
    if m:
        return ApunteInterpretado(
            tipo="gasto", concepto=m.group(2).strip(), importe=_a_decimal(m.group(1))
        )

    m = _RE_PENDIENTE.match(texto)
    if m:
        return ApunteInterpretado(
            tipo="trabajo",
            concepto=m.group(1).strip(),
            importe=_a_decimal(m.group(2)),
            pendiente=True,
        )

    m = _RE_TRABAJO.match(texto)
    if m:
        return ApunteInterpretado(
            tipo="trabajo", concepto=m.group(1).strip(), importe=_a_decimal(m.group(2))
        )

    raise TextoNoInterpretable(f"no se reconoce un importe al final de: '{texto}'")
