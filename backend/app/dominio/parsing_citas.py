"""Interpreta el texto de una cita escrito deprisa desde el móvil.

Formatos que entiende, todos opcionales salvo el título:
  "manana 10:00 Cambiar grifo"   -> mañana a las 10:00
  "hoy Pasar a cobrar"           -> hoy, sin hora
  "15/09 9h Reforma bano"        -> el 15 de septiembre a las 9:00
  "lunes 8:30 Montar radiador"   -> el próximo lunes
  "Cambiar grifo"                -> hoy, sin hora

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

_RE_FECHA = re.compile(r"^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?$")
# "10:00", "10.30", "9h", "9"a secas no: un número suelto suele ser parte del título.
_RE_HORA = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?h?$", re.IGNORECASE)


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


def _fecha_de(palabra: str, hoy: date) -> date | None:
    limpia = _sin_tildes(palabra)
    if limpia in ("hoy",):
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
        anio = int(anio) if anio else hoy.year
        if anio < 100:
            anio += 2000
        try:
            fecha = date(anio, int(mes), int(dia))
        except ValueError:
            return None
        # Sin año, una fecha ya pasada se entiende del año que viene.
        if not encaje.group(3) and fecha < hoy:
            fecha = fecha.replace(year=anio + 1)
        return fecha
    return None


def _hora_de(palabra: str) -> time | None:
    encaje = _RE_HORA.match(palabra)
    if not encaje:
        return None
    # Un número pelado solo es hora si lleva ":" o "h": "Reforma 3" es un título.
    if ":" not in palabra and "." not in palabra and not palabra.lower().endswith("h"):
        return None
    horas, minutos = encaje.groups()
    try:
        return time(int(horas), int(minutos or 0))
    except ValueError:
        return None


def interpretar_cita(texto: str, hoy: date) -> CitaInterpretada:
    palabras = texto.strip().split()
    if not palabras:
        raise CitaNoInterpretable("no has escrito nada")

    fecha = _fecha_de(palabras[0], hoy)
    if fecha is not None:
        palabras = palabras[1:]
    else:
        fecha = hoy

    hora = _hora_de(palabras[0]) if palabras else None
    if hora is not None:
        palabras = palabras[1:]

    titulo = " ".join(palabras).strip()
    if not titulo:
        raise CitaNoInterpretable("falta decir qué hay que hacer")

    return CitaInterpretada(fecha=fecha, titulo=titulo, hora=hora)
