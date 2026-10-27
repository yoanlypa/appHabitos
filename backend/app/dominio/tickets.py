"""Qué se acepta de lo que el modelo dice haber leído en un ticket. Reglas puras.

Un modelo con visión acierta mucho, pero cuando falla no avisa: devuelve un
número con la misma seguridad. Aquí se filtra lo que no puede ser verdad,
para que el formulario llegue vacío en vez de relleno con algo absurdo — un
hueco se ve, un 2340 donde iba 23,40 se cuela.

- El total tiene que ser positivo y razonable para un ticket (< 100.000 €).
- Admite "23,40", "23.40", "1.234,50" y "23,40 €", porque el modelo a veces
  copia el formato del ticket en vez de hacer caso.
- Una fecha en el futuro o de hace más de dos años no es la del ticket: es
  una lectura mala (un 2062 por un 2026). Se descarta y se usa hoy.
- El IVA no puede ser mayor que el total.
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TOTAL_MAXIMO = Decimal("100000")
_ANTIGUEDAD_MAXIMA = timedelta(days=730)


@dataclass
class DatosTicket:
    total: Decimal | None
    fecha: date | None
    comercio: str | None
    iva: Decimal | None
    concepto: str | None

    @property
    def concepto_sugerido(self) -> str:
        """Lo que irá como concepto del gasto si nadie lo cambia."""
        partes = [p for p in (self.concepto, self.comercio) if p]
        if len(partes) == 2 and partes[0].lower() == partes[1].lower():
            partes = partes[:1]
        return " · ".join(partes) or "Ticket escaneado"


def _importe(valor) -> Decimal | None:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        texto = str(valor)
    else:
        texto = re.sub(r"[^\d,.\-]", "", str(valor))
        if not texto:
            return None
        # "1.234,50" → "1234.50"; "23,40" → "23.40"; "1,234.50" → "1234.50"
        if "," in texto and "." in texto:
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        else:
            texto = texto.replace(",", ".")
    try:
        importe = Decimal(texto)
    except InvalidOperation:
        return None
    if not importe.is_finite():
        return None
    return importe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fecha(valor, hoy: date) -> date | None:
    if not isinstance(valor, str):
        return None
    try:
        leida = date.fromisoformat(valor.strip()[:10])
    except ValueError:
        return None
    if leida > hoy or hoy - leida > _ANTIGUEDAD_MAXIMA:
        return None
    return leida


def _texto(valor, largo: int) -> str | None:
    if not isinstance(valor, str):
        return None
    limpio = " ".join(valor.split())
    return limpio[:largo] or None


def interpretar_lectura(datos: dict, hoy: date) -> DatosTicket:
    total = _importe(datos.get("total"))
    if total is not None and not (Decimal("0") < total < TOTAL_MAXIMO):
        total = None

    iva = _importe(datos.get("iva"))
    if iva is not None and (iva < 0 or (total is not None and iva >= total)):
        iva = None

    return DatosTicket(
        total=total,
        fecha=_fecha(datos.get("fecha"), hoy),
        comercio=_texto(datos.get("comercio"), 60),
        iva=iva,
        concepto=_texto(datos.get("concepto"), 60),
    )
