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
- El IVA no puede ser mayor que el total, ni la base imponible tampoco.
- Las líneas sin descripción se descartan; las demás se guardan aunque les
  falte algún número, que la descripción sola ya dice qué se compró.
- Las esquinas solo valen si son cuatro puntos dentro de la foto.
- Los vales (cheques de devolución, cupones) caducados no se guardan.
"""
import re
from dataclasses import dataclass, field
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
    # Todo lo demás que pone el ticket, ya limpio y listo para guardar como
    # JSON: líneas, CIF, número, base imponible, forma de pago...
    detalle: dict = field(default_factory=dict)
    # Las cuatro esquinas del papel que vio el modelo, en fracciones (0 a 1).
    # Solo una pista para enderezar: `nucleo/perspectiva.py` la comprueba.
    esquinas: list | None = None

    @property
    def concepto_sugerido(self) -> str:
        """Lo que irá como concepto del gasto si nadie lo cambia."""
        partes = [p for p in (self.concepto, self.comercio) if p]
        if len(partes) == 2 and partes[0].lower() == partes[1].lower():
            partes = partes[:1]
        return " · ".join(partes) or "Ticket escaneado"


def _importe(valor, decimales: int = 2) -> Decimal | None:
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
    return importe.quantize(Decimal(10) ** -decimales, rounding=ROUND_HALF_UP)


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


def _cantidad(valor) -> Decimal | None:
    """Unidades de una línea: positivas y razonables, con hasta 3 decimales (kg, l)."""
    numero = _importe(valor)
    if numero is None:
        try:
            numero = Decimal(str(valor).replace(",", ".")).quantize(Decimal("0.001"))
        except (InvalidOperation, ValueError):
            return None
    return numero if Decimal("0") < numero < Decimal("100000") else None


def _numero_texto(valor) -> str | None:
    importe = _importe(valor)
    return f"{importe:.2f}" if importe is not None else None


def _precio_texto(valor) -> str | None:
    """Precio unitario: con 3 decimales si los trae (gasolina a 1,637 €/l).

    Redondearlo a 1,64 hace que litros × precio ya no dé el importe, y en una
    revisión eso parece un ticket mal apuntado.
    """
    precio = _importe(valor, decimales=3)
    if precio is None:
        return None
    return f"{precio:.2f}" if precio == precio.quantize(Decimal("0.01")) else f"{precio:.3f}"


def _lineas(valor) -> list[dict]:
    """Las líneas de producto. Una línea sin descripción no sirve para nada."""
    if not isinstance(valor, list):
        return []
    lineas = []
    for bruta in valor[:200]:  # un ticket de 200 líneas ya es un supermercado entero
        if not isinstance(bruta, dict):
            continue
        descripcion = _texto(bruta.get("descripcion"), 120)
        if not descripcion:
            continue
        cantidad = _cantidad(bruta.get("cantidad"))
        lineas.append(
            {
                "descripcion": descripcion,
                "cantidad": f"{cantidad.normalize():f}" if cantidad is not None else None,
                "precio_unitario": _precio_texto(bruta.get("precio_unitario")),
                "importe": _numero_texto(bruta.get("importe")),
            }
        )
    return lineas


def _tipos_iva(valor) -> list[dict]:
    if not isinstance(valor, list):
        return []
    tipos = []
    for bruto in valor[:6]:
        if not isinstance(bruto, dict):
            continue
        tipo = _importe(bruto.get("tipo"))
        if tipo is None or not Decimal("0") <= tipo <= Decimal("30"):
            continue
        tipos.append(
            {
                "tipo": f"{tipo.normalize():f}",
                "base": _numero_texto(bruto.get("base")),
                "cuota": _numero_texto(bruto.get("cuota")),
            }
        )
    return tipos


def _esquinas(valor) -> list | None:
    """Cuatro puntos [x, y] entre 0 y 1, o nada."""
    if not isinstance(valor, list) or len(valor) != 4:
        return None
    puntos = []
    for punto in valor:
        if not isinstance(punto, (list, tuple)) or len(punto) != 2:
            return None
        try:
            x, y = float(punto[0]), float(punto[1])
        except (TypeError, ValueError):
            return None
        if not (-0.05 <= x <= 1.05 and -0.05 <= y <= 1.05):
            return None
        puntos.append([round(min(max(x, 0.0), 1.0), 4), round(min(max(y, 0.0), 1.0), 4)])
    return puntos


_TIPOS_VALE = {"cheque": "Cheque", "cupon": "Cupón", "vale": "Vale"}


def _vales(valor, hoy: date) -> list[dict]:
    """Lo que el ticket da para gastar después: cheques, cupones, vales.

    Un vale caducado no se guarda: apuntarlo como pendiente sería recordar
    algo que ya no se puede usar.
    """
    if not isinstance(valor, list):
        return []
    vales = []
    for bruto in valor[:5]:
        if not isinstance(bruto, dict) or bruto.get("tipo") not in _TIPOS_VALE:
            continue
        caduca = None
        if isinstance(bruto.get("caduca"), str):
            try:
                caduca = date.fromisoformat(bruto["caduca"].strip()[:10])
            except ValueError:
                caduca = None
        if caduca is not None and caduca < hoy:
            continue
        importe = _importe(bruto.get("importe"))
        if importe is not None and not Decimal("0") < importe < TOTAL_MAXIMO:
            importe = None
        codigo = _texto(bruto.get("codigo"), 40)
        vales.append(
            {
                "tipo": bruto["tipo"],
                "descripcion": _texto(bruto.get("descripcion"), 80),
                "importe": f"{importe:.2f}" if importe is not None else None,
                "codigo": re.sub(r"\s", "", codigo) if codigo else None,
                "caduca": caduca.isoformat() if caduca else None,
            }
        )
    return vales


def texto_de_vale(vale: dict, comercio: str | None) -> str:
    """La nota que queda en el buzón: qué es, cuánto, dónde, código y hasta cuándo.

    Todo en una línea, porque así se lee en el buzón y en /notas, y se
    enseña en la caja del súper sin abrir nada más.
    """
    descripcion = vale.get("descripcion") or _TIPOS_VALE.get(vale.get("tipo"), "Vale")
    partes = [f"🎟 {descripcion}"]
    if vale.get("importe"):
        entero, _, centimos = vale["importe"].partition(".")
        partes[0] += f" {entero},{centimos} €"
    if comercio:
        partes.append(comercio)
    if vale.get("codigo"):
        partes.append(f"cód. {vale['codigo']}")
    if vale.get("caduca"):
        a, m, d = vale["caduca"].split("-")
        partes.append(f"caduca {d}/{m}/{a}")
    return " · ".join(partes)


def interpretar_lectura(datos: dict, hoy: date) -> DatosTicket:
    total = _importe(datos.get("total"))
    if total is not None and not (Decimal("0") < total < TOTAL_MAXIMO):
        total = None

    iva = _importe(datos.get("iva"))
    if iva is not None and (iva < 0 or (total is not None and iva >= total)):
        iva = None

    base = _importe(datos.get("base_imponible"))
    if base is not None and (base <= 0 or (total is not None and base > total)):
        base = None
    descuento = _importe(datos.get("descuento"))
    if descuento is not None:
        descuento = abs(descuento)
    hora = _texto(datos.get("hora"), 5)
    if hora and not re.fullmatch(r"\d{1,2}:\d{2}", hora):
        hora = None
    documento = datos.get("documento")

    detalle = {
        "razon_social": _texto(datos.get("razon_social"), 120),
        "cif": _texto(datos.get("cif"), 20),
        "direccion": _texto(datos.get("direccion"), 160),
        "numero": _texto(datos.get("numero"), 60),
        "hora": hora,
        "lineas": _lineas(datos.get("lineas")),
        "base_imponible": f"{base:.2f}" if base is not None else None,
        "tipos_iva": _tipos_iva(datos.get("tipos_iva")),
        "descuento": f"{descuento:.2f}" if descuento else None,
        "forma_pago": _texto(datos.get("forma_pago"), 40),
        "documento": documento if documento in ("gasto", "devolucion") else None,
        "vales": _vales(datos.get("vales"), hoy),
    }

    return DatosTicket(
        total=total,
        fecha=_fecha(datos.get("fecha"), hoy),
        comercio=_texto(datos.get("comercio"), 60),
        iva=iva,
        concepto=_texto(datos.get("concepto"), 60),
        detalle={clave: valor for clave, valor in detalle.items() if valor not in (None, [], "")},
        esquinas=_esquinas(datos.get("esquinas")),
    )
