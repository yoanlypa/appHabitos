"""Interpreta el texto de una cita escrito deprisa desde el móvil.

Formatos que entiende, todos opcionales salvo el título:
  "manana 10:00 Cambiar grifo"    -> mañana a las 10:00
  "hoy Pasar a cobrar"            -> hoy, sin hora
  "15/09 9h Reforma bano"         -> el 15 de septiembre a las 9:00
  "20 septiembre 10am Ver casa"   -> el 20 de septiembre a las 10:00
  "para el 20 de septiembre ..."  -> lo mismo, dicho como se habla
  "lunes a las 8:30 Radiador"     -> el próximo lunes a las 8:30
  "Cambiar grifo"                 -> hoy, sin hora

Se escribe como se habla, no como se rellena un formulario: quien apunta
desde el móvil dice "20 septiembre" y "10am", no "20/09" y "10:00". Cuando
una de esas formas no se reconocía, la cita caía en el día de hoy y el texto
entero se quedaba de título — y una cita en el día equivocado se descubre
tarde y mal, igual que un trabajo colgado de la Ana equivocada.

Nada se consume si no se ha entendido: si "para casa" no es una fecha, esas
palabras siguen estando en el título. Es lo que permite admitir muletillas
("para", "el", "a las") sin arriesgarse a comerse parte de lo que se apuntó.

Vive en `dominio/` y no en `bot/` porque es una regla pura: la web podría
querer la misma caja de texto, y duplicarla sería repetir el error que
justificó toda la reescritura.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, time, timedelta

_DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}

# Con las abreviaturas de tres letras, que es como se escribe con prisa.
_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dic": 12,
}

# Muletillas que pueden ir delante de la fecha. Solo se saltan si detrás hay
# una fecha de verdad: "para casa" no puede perder el "para".
_ANTES_DE_LA_FECHA = {"para", "el", "los", "dia"}
_SUFIJOS_DE_HORA = {"am", "pm", "a.m.", "p.m.", "h", "hs", "horas"}

_RE_FECHA = re.compile(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$")
_RE_ANIO = re.compile(r"^\d{4}$")
# "10:00", "10.30", "9h", "10am", "10:30pm". Un "9" a secas solo cuenta como
# hora si se ha dicho "a las": si no, suele ser parte del título.
_RE_HORA = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?(am|pm|a\.m\.|p\.m\.|h|hs|horas)?$", re.IGNORECASE)


class CitaNoInterpretable(ValueError):
    """El texto no da ni para un título."""


@dataclass
class CitaInterpretada:
    fecha: date
    titulo: str
    hora: time | None = None


def _sin_tildes(palabra: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", palabra.lower()) if unicodedata.category(c) != "Mn"
    )


def _con_anio(dia: int, mes: int, anio: int | None, hoy: date) -> date | None:
    """Arma la fecha y, si no se dijo el año, entiende lo ya pasado del que viene."""
    try:
        fecha = date(anio or hoy.year, mes, dia)
    except ValueError:
        return None
    if anio is None and fecha < hoy:
        try:
            return fecha.replace(year=fecha.year + 1)
        except ValueError:  # 29 de febrero
            return None
    return fecha


def _fecha_de(palabra: str, hoy: date) -> date | None:
    """Las fechas que caben en una sola palabra: "hoy", "lunes", "15/09"."""
    limpia = _sin_tildes(palabra)
    if limpia == "hoy":
        return hoy
    if limpia in ("manana", "mnn"):
        return hoy + timedelta(days=1)
    if limpia == "pasado":
        return hoy + timedelta(days=2)
    if limpia in _DIAS_SEMANA:
        # El próximo día con ese nombre; si hoy es ese día, la semana que viene.
        avance = (_DIAS_SEMANA[limpia] - hoy.weekday()) % 7 or 7
        return hoy + timedelta(days=avance)

    encaje = _RE_FECHA.match(limpia)
    if encaje:
        dia, mes, anio = encaje.groups()
        if anio is not None:
            anio = int(anio)
            if anio < 100:
                anio += 2000
        return _con_anio(int(dia), int(mes), anio, hoy)
    return None


def _leer_fecha(palabras: list[str], hoy: date) -> tuple[date | None, list[str]]:
    """Se come la fecha del principio si la hay, y devuelve lo que queda.

    Si no la hay, devuelve la lista tal cual: ni una palabra se pierde por
    haber intentado leerla.
    """
    saltos = 0
    while saltos < len(palabras) and _sin_tildes(palabras[saltos]) in _ANTES_DE_LA_FECHA:
        saltos += 1
    resto = palabras[saltos:]
    if not resto:
        return None, palabras

    de_una_palabra = _fecha_de(resto[0], hoy)
    if de_una_palabra is not None:
        return de_una_palabra, resto[1:]

    # "20 septiembre", "20 de septiembre", "20 de septiembre de 2027"
    if resto[0].isdigit():
        i = 1
        if i < len(resto) and _sin_tildes(resto[i]) == "de":
            i += 1
        if i < len(resto):
            mes = _MESES.get(_sin_tildes(resto[i]).rstrip("."))
            if mes is not None:
                i += 1
                anio = None
                j = i + 1 if i < len(resto) and _sin_tildes(resto[i]) == "de" else i
                if j < len(resto) and _RE_ANIO.match(resto[j]):
                    anio = int(resto[j])
                    i = j + 1
                fecha = _con_anio(int(resto[0]), mes, anio, hoy)
                if fecha is not None:
                    return fecha, resto[i:]

    return None, palabras


def _hora_de(palabra: str, admite_numero_pelado: bool = False) -> time | None:
    encaje = _RE_HORA.match(palabra)
    if not encaje:
        return None
    horas, minutos, sufijo = encaje.groups()
    sufijo = (sufijo or "").lower().replace(".", "")

    # Un número pelado solo es hora si se ha dicho "a las": "Reforma 3" es un título.
    if not sufijo and ":" not in palabra and "." not in palabra and not admite_numero_pelado:
        return None

    horas = int(horas)
    if sufijo in ("am", "pm"):
        if horas > 12:
            return None
        if sufijo == "pm" and horas != 12:
            horas += 12
        if sufijo == "am" and horas == 12:
            horas = 0
    try:
        return time(horas, int(minutos or 0))
    except ValueError:
        return None


def _leer_hora(palabras: list[str]) -> tuple[time | None, list[str]]:
    """Igual que la fecha: solo se come lo que ha entendido."""
    if not palabras:
        return None, palabras

    # "a las 10" deja claro que el número es una hora, aunque vaya pelado.
    dicho_con_letras = False
    resto = palabras
    if len(palabras) >= 2 and _sin_tildes(palabras[0]) == "a" and _sin_tildes(palabras[1]) == "las":
        resto, dicho_con_letras = palabras[2:], True
    elif _sin_tildes(palabras[0]) in ("alas", "las"):
        resto, dicho_con_letras = palabras[1:], True
    if not resto:
        return None, palabras

    # "10 am" separado en dos palabras es lo que sale del teclado del móvil.
    trozo, largo = resto[0], 1
    if len(resto) >= 2 and _sin_tildes(resto[1]) in _SUFIJOS_DE_HORA:
        trozo, largo = resto[0] + _sin_tildes(resto[1]), 2

    hora = _hora_de(trozo, admite_numero_pelado=dicho_con_letras)
    if hora is not None:
        return hora, resto[largo:]
    return None, palabras


def interpretar_cita(texto: str, hoy: date) -> CitaInterpretada:
    palabras = texto.strip().split()
    if not palabras:
        raise CitaNoInterpretable("no has escrito nada")

    fecha, palabras = _leer_fecha(palabras, hoy)
    hora, palabras = _leer_hora(palabras)
    # La hora puede ir delante de la fecha: "a las 10 del 20 de septiembre".
    if fecha is None:
        fecha, palabras = _leer_fecha(palabras, hoy)

    titulo = " ".join(palabras).strip()
    if not titulo:
        raise CitaNoInterpretable("falta decir qué hay que hacer")

    return CitaInterpretada(fecha=fecha or hoy, titulo=titulo, hora=hora)
