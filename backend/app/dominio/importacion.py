"""Leer varios movimientos de golpe: líneas, una tabla o lo que leyó la IA.

Nace de once tickets de parking: anotarlos uno a uno eran once mensajes y
once `/fecha`. Aquí están las tres formas de traerlos juntos, las tres con
la misma salida (`Movimiento`) para que lo que venga después —enseñar la
lista, quitar repetidos, guardar— sea una sola cosa:

- `leer_lineas`: un mensaje con un apunte por línea.
- `leer_tabla`: las filas de un CSV o un Excel hecho a mano o exportado de
  otra app. Más tolerante que `copia_csv.py`, que solo lee las copias del
  propio bot y es estricto adrede.
- `de_lectura`: lo que contesta el modelo al mirar una captura con varios
  pagos. Se filtra antes de creérselo, igual que un ticket.

Reglas puras: ni base de datos, ni Telegram, ni red.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.dominio.parsing import TextoNoInterpretable, interpretar_con_fecha

# Más allá de esto no es "unos cuantos movimientos": es otra cosa, y enseñar
# la lista antes de guardar deja de servir para nada.
MAXIMO = 200
_IMPORTE_MAXIMO = Decimal("100000")
# Lo que Hacienda puede pedir. Más viejo que eso es una fecha mal leída.
_ANTIGUEDAD_MAXIMA = timedelta(days=5 * 366)


class ImportacionNoValida(ValueError):
    """De ahí no se pueden sacar movimientos."""


@dataclass(frozen=True)
class Movimiento:
    fecha: date
    # None = la fuente no dice si entra o sale (una tabla sin columna de tipo
    # y sin signos). Entonces se pregunta; nunca se supone.
    tipo: str | None  # "trabajo" | "gasto" | None
    concepto: str
    importe: Decimal
    pendiente: bool = False


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )


# --- Un apunte por línea -----------------------------------------------------


def leer_lineas(texto: str, hoy: date) -> list[Movimiento] | None:
    """Los movimientos de un mensaje de varias líneas, o None si no lo es.

    Solo cuenta como lista si hay al menos dos líneas y TODAS son un apunte
    con su importe. Una nota larga con saltos de línea (la lista de la
    compra) tiene que seguir siendo una nota: si una sola línea no lleva
    importe, esto no es una importación.
    """
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    if len(lineas) < 2 or len(lineas) > MAXIMO:
        return None
    movimientos = []
    for linea in lineas:
        try:
            interpretado, fecha = interpretar_con_fecha(linea, hoy)
        except TextoNoInterpretable:
            return None
        if interpretado.importe <= 0:
            return None
        movimientos.append(
            Movimiento(
                fecha=fecha or hoy,
                tipo=interpretado.tipo,
                concepto=interpretado.concepto,
                importe=interpretado.importe,
                pendiente=interpretado.pendiente,
            )
        )
    return movimientos


# --- Una tabla (CSV o Excel) -------------------------------------------------

_COLUMNAS = {
    "fecha": {"fecha", "dia", "date", "fecha operacion", "fecha valor", "f. valor", "f valor"},
    "concepto": {
        "concepto", "descripcion", "detalle", "nombre", "movimiento", "comercio", "titulo",
        "description", "asunto",
    },
    "importe": {"importe", "cantidad", "total", "precio", "amount", "euros", "importe (eur)", "valor"},
    "tipo": {"tipo", "type", "clase"},
    "pendiente": {"pendiente", "sin cobrar"},
}
_GASTO = {"gasto", "gastos", "pago", "cargo", "compra", "salida", "expense"}
_TRABAJO = {"trabajo", "ingreso", "ingresos", "cobro", "abono", "entrada", "venta", "income"}
_SI = {"si", "true", "1", "verdadero", "x"}


def filas_de_csv(texto: str) -> list[list[str]]:
    """El CSV partido en celdas, con coma o con punto y coma (el de Excel en español)."""
    texto = texto.lstrip("﻿")
    primera = texto.split("\n", 1)[0]
    separador = max(";,\t", key=primera.count)
    return [fila for fila in csv.reader(io.StringIO(texto), delimiter=separador)]


def _fecha(valor: str) -> date:
    limpio = valor.strip().split("T")[0].split(" ")[0]
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(limpio, formato).date()
        except ValueError:
            continue
    raise ValueError(f"fecha '{valor}' no reconocida")


def _importe(valor: str) -> Decimal:
    """El importe con su signo: en un extracto, el menos es lo que dice que es un gasto."""
    limpio = valor.strip().replace("€", "").replace("EUR", "").replace("eur", "")
    limpio = limpio.replace("−", "-").replace(" ", "").replace(" ", "")
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
    if not importe.is_finite() or importe == 0:
        raise ValueError(f"importe '{valor}' no reconocido")
    if importe.as_tuple().exponent < -2:
        # 2.7500000001 de un Excel es 2,75; 2,755 no se sabe qué es.
        redondeado = importe.quantize(Decimal("0.01"))
        if abs(redondeado - importe) > Decimal("0.0001"):
            raise ValueError(f"importe '{valor}' con más de dos decimales")
        importe = redondeado
    if abs(importe) >= _IMPORTE_MAXIMO:
        raise ValueError(f"importe '{valor}' demasiado grande")
    return importe


def _tipo(valor: str) -> str | None:
    limpio = _sin_tildes(valor.strip())
    if limpio in _GASTO:
        return "gasto"
    if limpio in _TRABAJO:
        return "trabajo"
    if not limpio:
        return None
    raise ValueError(f"tipo '{valor}' desconocido")


def leer_tabla(filas: list[list[str]], hoy: date) -> list[Movimiento]:
    """Los movimientos de una tabla con cabecera.

    Hacen falta tres columnas: fecha, concepto e importe, con esos nombres o
    los parecidos de `_COLUMNAS`. `tipo` es opcional: si falta, un importe
    negativo es un gasto; y si todo es positivo, el tipo queda en None para
    preguntarlo. Suponer "gasto" o "cobro" para una tabla entera sería
    equivocarse en bloque.

    Como en la copia: si una fila está mal, no se lee ninguna. Importar a
    medias sin saber qué se quedó fuera es peor que no importar.
    """
    filas = [fila for fila in filas if any((celda or "").strip() for celda in fila)]
    if not filas:
        raise ImportacionNoValida("el fichero está vacío")

    cabecera = [_sin_tildes((celda or "").strip()) for celda in filas[0]]
    donde: dict[str, int] = {}
    for columna, nombres in _COLUMNAS.items():
        for indice, celda in enumerate(cabecera):
            if celda in nombres:
                donde[columna] = indice
                break
    faltan = [c for c in ("fecha", "concepto", "importe") if c not in donde]
    if faltan:
        raise ImportacionNoValida(
            f"no encuentro la columna {', '.join(faltan)} en la primera fila. "
            "Tiene que haber tres con estos nombres: fecha, concepto, importe"
        )
    if len(filas) - 1 > MAXIMO:
        raise ImportacionNoValida(f"son más de {MAXIMO} filas; pártelo en varios ficheros")

    def celda(fila: list[str], columna: str) -> str:
        indice = donde.get(columna)
        return (fila[indice] or "").strip() if indice is not None and indice < len(fila) else ""

    crudos: list[tuple[date, str | None, str, Decimal, bool]] = []
    errores: list[str] = []
    for numero, fila in enumerate(filas[1:], start=2):
        try:
            concepto = " ".join(celda(fila, "concepto").split())
            if not concepto:
                raise ValueError("sin concepto")
            fecha = _fecha(celda(fila, "fecha"))
            if fecha > hoy:
                raise ValueError(f"fecha futura ({fecha:%d/%m/%Y})")
            crudos.append(
                (
                    fecha,
                    _tipo(celda(fila, "tipo")),
                    concepto[:200],
                    _importe(celda(fila, "importe")),
                    _sin_tildes(celda(fila, "pendiente")) in _SI,
                )
            )
        except ValueError as exc:
            errores.append(f"fila {numero}: {exc}")
    if errores:
        resto = f" (y {len(errores) - 3} más)" if len(errores) > 3 else ""
        raise ImportacionNoValida("; ".join(errores[:3]) + resto)
    if not crudos:
        raise ImportacionNoValida("no tiene ningún movimiento")

    # Con signos mezclados la tabla es un extracto: el menos es el gasto y lo
    # demás, dinero que entra. Sin ningún negativo no hay forma de saberlo.
    hay_negativos = any(importe < 0 for _, _, _, importe, _ in crudos)
    movimientos = []
    for fecha, tipo, concepto, importe, pendiente in crudos:
        if tipo is None and hay_negativos:
            tipo = "gasto" if importe < 0 else "trabajo"
        movimientos.append(
            Movimiento(
                fecha=fecha,
                tipo=tipo,
                concepto=concepto,
                importe=abs(importe),
                pendiente=pendiente and tipo == "trabajo",
            )
        )
    return movimientos


# --- Lo que leyó la IA en una captura ---------------------------------------


def de_lectura(datos: dict, hoy: date) -> list[Movimiento]:
    """Los movimientos que dio el modelo, quitando lo que no se sostiene.

    El modelo se equivoca sin avisar. Una fila sin fecha, con fecha futura o
    de hace más de cinco años, sin importe o con uno absurdo se descarta: un
    hueco se ve al repasar la lista, un número inventado se cuela.
    """
    crudos = datos.get("movimientos") if isinstance(datos, dict) else None
    if not isinstance(crudos, list):
        return []
    movimientos = []
    for crudo in crudos[:MAXIMO]:
        if not isinstance(crudo, dict):
            continue
        concepto = crudo.get("concepto")
        if not isinstance(concepto, str) or not concepto.strip():
            continue
        try:
            fecha = _fecha(str(crudo.get("fecha") or ""))
            importe = _importe(str(crudo.get("importe") if crudo.get("importe") is not None else ""))
        except ValueError:
            continue
        if fecha > hoy or hoy - fecha > _ANTIGUEDAD_MAXIMA:
            continue
        tipo = _sin_tildes(str(crudo.get("tipo") or "gasto"))
        movimientos.append(
            Movimiento(
                fecha=fecha,
                # Ante la duda, gasto: es lo que son casi todas las capturas (parking,
                # peajes, pedidos), y un gasto de más se ve; un ingreso inventado no.
                tipo="trabajo" if tipo in _TRABAJO else "gasto",
                concepto=" ".join(concepto.split())[:200],
                importe=abs(importe),
            )
        )
    return movimientos


_RE_MARCA_LISTA = re.compile(
    r"^\s*(?:lista|listado|varios|movimientos|historial|extracto)\s*[.:!]*\s*$", re.IGNORECASE
)


def marca_lista(texto: str | None) -> bool:
    """Si el texto de una foto dice que no es un ticket sino una lista de pagos.

    La palabra sola, sin nada más: "lista de materiales baño" es el concepto
    de un ticket, y tomarlo por la marca dejaría ese ticket sin anotar.
    """
    return bool(texto and _RE_MARCA_LISTA.match(texto))
