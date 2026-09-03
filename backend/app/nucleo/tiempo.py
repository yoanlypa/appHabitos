"""Hora y fecha locales según TZ_LOCAL.

Es infraestructura, no negocio: `nucleo/` puede saber qué hora es "ahora",
pero no qué significa eso para un apunte. `dominio/` y `servicios/` no
deben hardcodear una zona horaria fuera de aquí.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.nucleo.config import HORA_AVISO, TZ_LOCAL


def zona() -> ZoneInfo:
    return ZoneInfo(TZ_LOCAL)


def ahora_local() -> datetime:
    return datetime.now(zona())


def hoy_local() -> date:
    return ahora_local().date()


def hora_del_aviso() -> time:
    """`HORA_AVISO` ("HH:MM") ya con la zona puesta, como lo quiere el job diario."""
    horas, minutos = HORA_AVISO.split(":")
    return time(int(horas), int(minutos), tzinfo=zona())
