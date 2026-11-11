"""Interpreta texto libre (del bot o de la web) como un apunte.

Sin dependencias de FastAPI ni de Telegram para poder probarlo con casos
sueltos. Formatos reconocidos:
  "Cambio de grifo Ana 120"      -> trabajo cobrado, 120.00 EUR
  "pendiente Reforma baño 980"   -> trabajo sin cobrar, 980.00 EUR
  "-45 gasolina"                 -> gasto, 45.00 EUR

Y las mismas frases dichas en voz alta, que llegan aquí transcritas:
  "Cambio de grifo Ana 120 euros."  -> igual que la primera
  "gasto de 45 en gasolina"         -> gasto, 45.00 EUR
Nadie dicta un guion ni deja de decir "euros", así que si el parser no
admitiera esto, media nota de voz acabaría sin importe.

Y con el día delante, para lo que se apunta tarde (`interpretar_con_fecha`):
  "ayer -45 gasolina"            -> gasto de ayer
  "3/11 parking 2,75"            -> trabajo del 3 de noviembre
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.dominio.tickets import fecha_escrita

_NUMERO = r"\d+(?:[.,]\d{1,2})?"

_RE_GASTO = re.compile(rf"^-({_NUMERO})\s+(.+)$")
_RE_PENDIENTE = re.compile(rf"^pendiente\s+(.+?)\s+({_NUMERO})$", re.IGNORECASE)
_RE_TRABAJO = re.compile(rf"^(.+?)\s+({_NUMERO})$")

# Al dictar se dice "gasto de 45 en gasolina": el guion de "-45" no se
# pronuncia. El importe puede quedar delante o detrás del concepto.
# Solo vale la palabra "gasto", nada de "menos" ni "pagado": "menos mal que
# vino Ana 120" es un trabajo, y "pagado" lo dice quien te paga a ti.
_RE_GASTO_HABLADO = re.compile(r"^gastos?\s+(?:de\s+|en\s+)?(.+)$", re.IGNORECASE)
_RE_IMPORTE_DELANTE = re.compile(
    rf"^({_NUMERO})\s*(?:€|eur|euros?)?\s+(?:de\s+|en\s+|para\s+)?(.+)$", re.IGNORECASE
)
_RE_IMPORTE_DETRAS = re.compile(rf"^(.+?)\s+({_NUMERO})$")

# "euros", "€" y el punto final que pone el transcriptor. Se quitan antes de
# buscar el importe porque el resto de reglas lo esperan al final del todo.
# El \b va solo detrás de las letras: el símbolo no es carácter de palabra y
# al final del texto no hay frontera que valga, así que "980 €" no casaría.
_RE_COLA = re.compile(r"(?:\s*(?:€|euros?\b|eur\b)|[.;:!?¡¿]+)\s*$", re.IGNORECASE)


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


def _limpiar(texto: str) -> str:
    """Quita la moneda y la puntuación del final, tantas veces como haga falta.

    "120 euros." lleva las dos, y en ese orden: primero se va el punto y
    luego "euros", que hasta entonces no estaba al final.
    """
    texto = texto.strip()
    while True:
        recortado = _RE_COLA.sub("", texto).strip()
        if recortado == texto:
            return texto
        texto = recortado


def interpretar_texto(texto: str) -> ApunteInterpretado:
    texto = _limpiar(texto)
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

    m = _RE_GASTO_HABLADO.match(texto)
    if m:
        resto = m.group(1).strip()
        for regla, grupo_concepto, grupo_importe in (
            (_RE_IMPORTE_DELANTE, 2, 1),
            (_RE_IMPORTE_DETRAS, 1, 2),
        ):
            trozos = regla.match(resto)
            # Sin concepto no hay concepto: "gasto de 12 euros en tornillos"
            # no puede quedar como "euros en tornillos".
            if trozos and _limpiar(trozos.group(grupo_concepto)):
                return ApunteInterpretado(
                    tipo="gasto",
                    concepto=_limpiar(trozos.group(grupo_concepto)),
                    importe=_a_decimal(trozos.group(grupo_importe)),
                )

        # "gasto de 45 euros" y nada más. Se guarda igualmente como gasto:
        # dejarlo caer a la regla de trabajo lo apuntaría como dinero que
        # entra, que es el error que más caro sale de todos.
        solo_importe = re.fullmatch(_NUMERO, _limpiar(resto))
        if solo_importe:
            return ApunteInterpretado(
                tipo="gasto", concepto="Gasto", importe=_a_decimal(solo_importe.group(0))
            )

    m = _RE_TRABAJO.match(texto)
    if m:
        return ApunteInterpretado(
            tipo="trabajo", concepto=m.group(1).strip(), importe=_a_decimal(m.group(2))
        )

    raise TextoNoInterpretable(f"no se reconoce un importe al final de: '{texto}'")


def interpretar_con_fecha(texto: str, hoy: date) -> tuple[ApunteInterpretado, date | None]:
    """Lo mismo, admitiendo el día delante: "ayer -45 gasolina", "3/11 parking 2,75".

    Lo que se apunta tarde es lo que antes obligaba a un `/fecha 34 15/10`
    después, con el número del apunte de memoria. La fecha se lee como la de
    un ticket (del pasado: "15/12" sin año es el último 15 de diciembre) y
    vale la regla de siempre: nada se consume si no se ha entendido. Si lo
    que queda tras la fecha no es un apunte con su importe, el texto se
    interpreta entero, como hasta ahora: "15/10 llamar a Ana" sigue siendo
    una nota con su "15/10" dentro.

    Devuelve None de fecha cuando no se escribió ninguna (es de hoy).
    """
    palabras = texto.split()
    if palabras and _sin_tildes(palabras[0]) == "anteayer":
        fecha, resto = hoy - timedelta(days=2), " ".join(palabras[1:])
    else:
        fecha, resto = fecha_escrita(texto, hoy)
    if fecha is not None and resto.strip():
        try:
            return interpretar_texto(resto), fecha
        except TextoNoInterpretable:
            pass
    return interpretar_texto(texto), None


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


# Palabras que casi nunca son un trabajo cobrado. "gasolina 45" sin guion se
# apunta como dinero que entra (es la regla, y está avisada), pero es justo
# el error que más caro sale: con esto el bot puede preguntar en el momento.
# La lista es corta a propósito. "material" o "pintura" no están: se le
# cobran al cliente tantas veces como se compran.
_SUENA_A_GASTO = (
    "gasolina", "gasoil", "gasoleo", "diesel", "repostaje", "combustible",
    "parking", "aparcamiento", "parquimetro", "peaje", "autopista",
    "ferreteria", "leroy", "bricomart", "obramat", "bauhaus", "bricodepot",
    "mercadona", "supermercado", "desayuno", "almuerzo", "comida", "cena", "cafe",
    "autonomos", "gestoria", "seguro", "itv", "taller", "multa",
    "telefono", "movil", "internet", "alquiler", "luz", "hosting", "dominio",
)


def suena_a_gasto(concepto: str) -> str | None:
    """La palabra del concepto que delata un gasto, o None.

    Solo palabras enteras: "Luz Marina" lleva "luz", pero ahí manda que un
    cliente nombrado no se pregunta (eso lo decide quien llama).
    """
    for palabra in re.findall(r"[a-z0-9]+", _sin_tildes(concepto)):
        if palabra in _SUENA_A_GASTO:
            return palabra
    return None
