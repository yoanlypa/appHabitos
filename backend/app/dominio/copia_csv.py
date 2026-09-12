"""Leer una copia de seguridad en CSV, para poder volver a meterla.

Una copia que no se puede restaurar es media copia. El bot manda cada
domingo el histórico entero por Telegram (`bot/copias.py`), pero no había
forma de hacer el camino de vuelta, y los datos ya se han perdido dos veces.

Lee el fichero tal cual lo manda el bot (utf-8 con BOM, separado por comas,
importes con punto) y también el que sale de abrirlo y guardarlo con Excel
en español: punto y coma, importes con coma, fechas como 10/09/2026 y a veces
otra codificación. Es lo que pasa en cuanto alguien lo toca, y la copia
tiene que seguir sirviendo.

Si una sola línea está mal, no se lee nada. Restaurar a medias, sin saber
qué se quedó fuera, deja las cuentas peor que no restaurar.

Regla pura: no toca la base de datos. Eso es cosa de
`servicios/restauracion.py`.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

COLUMNAS = ("fecha", "tipo", "concepto", "importe", "pendiente", "origen")
_TIPOS = {"trabajo", "gasto", "nota"}
_SI = {"si", "sí", "true", "1", "verdadero", "x"}
_NO = {"no", "false", "0", "falso", ""}


class CopiaNoValida(ValueError):
    """El fichero no es una copia que se pueda restaurar."""


@dataclass(frozen=True)
class FilaCopia:
    fecha: date
    tipo: str
    concepto: str
    importe: Decimal
    pendiente: bool
    origen: str


def decodificar(datos: bytes) -> str:
    """utf-8 (con o sin BOM), que es lo que manda el bot; si no, lo de Excel."""
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        return datos.decode("cp1252")
    except UnicodeDecodeError as exc:
        raise CopiaNoValida("no parece un fichero de texto") from exc


def _fecha(valor: str) -> date:
    limpio = valor.strip()
    try:
        return date.fromisoformat(limpio)
    except ValueError:
        pass
    try:
        return datetime.strptime(limpio, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValueError(f"fecha '{valor}' no reconocida") from exc


def _importe(valor: str) -> Decimal:
    limpio = valor.strip().replace("€", "").replace(" ", "")
    if "," in limpio and "." in limpio:
        # El separador que va más a la derecha es el de los decimales.
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    else:
        limpio = limpio.replace(",", ".")
    try:
        importe = Decimal(limpio)
    except InvalidOperation as exc:
        raise ValueError(f"importe '{valor}' no reconocido") from exc
    if not importe.is_finite():
        raise ValueError(f"importe '{valor}' no reconocido")
    if importe < 0:
        raise ValueError(f"importe negativo '{valor}': los gastos se guardan en positivo")
    # Con tres decimales, el paso a céntimos redondearía en silencio: mejor
    # pararse que meter una cifra que no es la que había.
    if importe.as_tuple().exponent < -2:
        raise ValueError(f"importe '{valor}' con más de dos decimales")
    return importe


def _pendiente(valor: str) -> bool:
    limpio = valor.strip().lower()
    if limpio in _SI:
        return True
    if limpio in _NO:
        return False
    raise ValueError(f"pendiente '{valor}' no es ni sí ni no")


def leer_copia(texto: str) -> list[FilaCopia]:
    texto = texto.lstrip("﻿")
    primera = texto.split("\n", 1)[0]
    # Excel en español guarda con punto y coma, porque la coma es su decimal.
    separador = ";" if primera.count(";") > primera.count(",") else ","
    lector = csv.DictReader(io.StringIO(texto), delimiter=separador)

    cabecera = [(columna or "").strip().lower() for columna in (lector.fieldnames or [])]
    faltan = [columna for columna in COLUMNAS if columna not in cabecera]
    if faltan:
        raise CopiaNoValida(f"le faltan las columnas {', '.join(faltan)}")
    lector.fieldnames = cabecera

    filas: list[FilaCopia] = []
    errores: list[str] = []
    for registro in lector:
        # La clave None recoge columnas de más; no son de la copia.
        valores = {clave: (valor or "") for clave, valor in registro.items() if clave}
        if not any(valor.strip() for valor in valores.values()):
            continue
        try:
            tipo = valores["tipo"].strip().lower()
            if tipo not in _TIPOS:
                raise ValueError(f"tipo '{valores['tipo']}' desconocido")
            concepto = valores["concepto"].strip()
            if not concepto:
                raise ValueError("sin concepto")
            filas.append(
                FilaCopia(
                    fecha=_fecha(valores["fecha"]),
                    tipo=tipo,
                    concepto=concepto,
                    importe=_importe(valores["importe"]),
                    pendiente=_pendiente(valores["pendiente"]),
                    origen=valores["origen"].strip() or "copia",
                )
            )
        except ValueError as exc:
            errores.append(f"línea {lector.line_num}: {exc}")

    if errores:
        resto = f" (y {len(errores) - 3} más)" if len(errores) > 3 else ""
        raise CopiaNoValida("; ".join(errores[:3]) + resto)
    if not filas:
        raise CopiaNoValida("no tiene ningún apunte")
    return filas
