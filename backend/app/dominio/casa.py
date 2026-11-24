"""Reglas puras de la casa: entender lo que se escribe, categorías y la lista.

Casa es el dinero y la compra del hogar, compartidos entre Yoa y su esposa.
Va aparte del negocio a propósito, en sus propias tablas: un gasto del súper
no puede acabar nunca en el trimestre, en el modelo 130 ni en la gestoría, y
la forma de que no pase es que esas cuentas ni lo vean.

Aquí no hay base de datos: interpretar "-45 súper", decidir que es del súper,
partir "leche, huevos y pan" en tres cosas y saber si una línea de un ticket
es algo de la lista. Se prueba sin arrancar nada.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.dominio.parsing import TextoNoInterpretable, interpretar_con_fecha

CATEGORIAS = ["Súper", "Casa", "Facturas", "Salud", "Coche", "Niños", "Ropa", "Ocio", "Comer fuera", "Otros"]

# De más concreto a más general: la primera que case gana. Palabras sueltas
# y nombres de tiendas, comparados sin tildes ni mayúsculas.
_PALABRAS = [
    ("Comer fuera", ["restaurante", "bar ", "cafeteria", "cafe ", "menu", "burger", "pizza", "kebab", "telepizza", "glovo", "just eat", "uber eats", "mcdonald", "kfc", "tapas"]),
    ("Facturas", ["luz", "agua", "gas ", "butano", "internet", "fibra", "movil", "telefono", "alquiler", "hipoteca", "comunidad", "seguro hogar", "endesa", "iberdrola", "naturgy", "movistar", "vodafone", "orange", "digi", "netflix", "spotify", "suscripcion", "emasa", "ibi"]),
    ("Súper", ["super", "mercadona", "lidl", "aldi", "carrefour", "dia ", "eroski", "alcampo", "hipercor", "consum", "ahorramas", "compra", "fruteria", "carniceria", "pescaderia", "panaderia", "pan ", "leche", "huevos", "fruta", "verdura"]),
    ("Salud", ["farmacia", "medico", "dentista", "optica", "medicina", "pastillas", "clinica", "hospital", "fisio"]),
    ("Coche", ["gasolina", "gasoil", "diesel", "repsol", "cepsa", "ballenoil", "taller", "itv", "parking", "peaje", "ruedas", "lavado"]),
    ("Niños", ["colegio", "guarderia", "cole ", "libros", "material escolar", "pañales", "panales", "juguete", "extraescolar", "comedor", "niño", "nino", "niña", "nina", "bebe"]),
    ("Ropa", ["ropa", "zapatos", "zapatillas", "zara", "primark", "decathlon", "h&m", "pull", "bershka", "shein"]),
    ("Ocio", ["cine", "entradas", "viaje", "hotel", "regalo", "cumpleaños", "cumpleanos", "gimnasio", "amazon"]),
    ("Casa", ["ikea", "leroy", "bricomart", "mueble", "limpieza", "lavadora", "electrodomestico", "menaje", "ferreteria", "drogueria"]),
]


def sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in normal if unicodedata.category(c) != "Mn")


def categoria_de(concepto: str) -> str:
    """La categoría que más se le parece. Ante la duda, "Otros": se cambia con un toque."""
    texto = f" {sin_tildes(concepto)} "
    for categoria, palabras in _PALABRAS:
        if any(p in texto or p.strip() == texto.strip() for p in palabras):
            return categoria
    return "Otros"


@dataclass
class GastoLeido:
    concepto: str
    importe: Decimal
    fecha: date | None  # None: hoy


def interpretar_gasto(texto: str, hoy: date) -> GastoLeido | None:
    """Un gasto de casa escrito como en el bot: "-45 súper", "súper 45", "ayer 12,50 farmacia".

    En casa todo lo que lleva importe es un gasto: aquí no se cobra a
    clientes, así que "súper 45" sin guion no puede ser dinero que entra.
    Sin importe devuelve None (será algo para la lista, o nada).
    """
    try:
        leido, fecha = interpretar_con_fecha(texto, hoy)
    except TextoNoInterpretable:
        # Dictado o escrito con prisa, el número va en medio: "pagué 60 de
        # luz", "ayer 12,50 farmacia". Si hay UN solo número suelto, se pasa
        # al final y se vuelve a probar. Con dos no se adivina cuál es.
        numeros = list(_RE_NUMERO_SUELTO.finditer(texto))
        if len(numeros) != 1:
            return None
        n = numeros[0]
        # "2 kilos de tomates" o "comprar 6 huevos" son cosas de la lista,
        # no 2 € ni 6 €: el número en medio solo es dinero si algo lo dice.
        # Delante ("45 súper") es como se dice un gasto, salvo cantidades
        # pequeñas: "6 huevos" es para la lista.
        delante = not texto[: n.start()].strip() or _RE_FECHA_DELANTE.match(texto[: n.start()])
        con_decimales = "," in n.group(1) or "." in n.group(1)
        if not (_ES_DINERO.search(texto) or con_decimales or (delante and int(n.group(1)) >= 10)):
            return None
        if _RE_UNIDAD.match(texto[n.end():]):
            return None
        resto = (texto[: n.start()] + " " + texto[n.end():]).strip()
        resto = re.sub(r"\s+(de|en)\s*$", "", re.sub(r"\s+", " ", resto))
        try:
            leido, fecha = interpretar_con_fecha(f"{resto} {n.group(1)}", hoy)
        except TextoNoInterpretable:
            return None
    concepto = re.sub(r"^\s*(?:gasto|pago|pagado|pague|pagué|he\s+pagado|gastado|gaste|gasté)\s+(?:de\s+|en\s+)?", "", leido.concepto, flags=re.I)
    concepto = re.sub(r"^\s*(?:de|en)\s+", "", concepto, flags=re.I)
    if not concepto.strip() or leido.importe <= 0:
        return None
    return GastoLeido(concepto=concepto.strip()[:1].upper() + concepto.strip()[1:], importe=leido.importe, fecha=fecha)


# Un número que no forma parte de una fecha (3/11) ni de otra cosa.
_RE_NUMERO_SUELTO = re.compile(r"(?<![\w/.,-])(\d+(?:[.,]\d{1,2})?)(?:\s*(?:€|euros?\b))?(?![\w/.,]\d|[/\w])")


_RE_FECHA_DELANTE = re.compile(r"^\s*(?:hoy|ayer|anteayer|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*$", re.I)
_ES_DINERO = re.compile(r"€|\beuros?\b|\b(?:pagu[eé]|pagado|pago|gasto|gastado|gast[eé]|cost[oó]|me\s+cobraron)\b", re.I)
_RE_UNIDAD = re.compile(r"\s*(?:kg|kilos?|g|gr|gramos|l|litros?|ud|uds|unidades|paquetes?|latas?|botes?|docenas?|bolsas?|botellas?|cajas?|piezas?)\b", re.I)


# "casa -45 súper": el prefijo con el que Yoa manda algo a casa desde donde
# normalmente anota el negocio.
_RE_CASA = re.compile(r"^\s*casa\b[\s:,]*", re.IGNORECASE)


def quitar_prefijo_casa(texto: str | None) -> tuple[bool, str]:
    if not texto or not _RE_CASA.match(texto):
        return False, texto or ""
    return True, _RE_CASA.sub("", texto, count=1).strip()


# "comprar leche", "lista: pan", "añade huevos a la lista", "+ tomates".
_RE_LISTA = re.compile(
    r"^\s*(?:\+|comprar|compra:|lista[:\s]|apunta(?:r)?\s+(?:en\s+la\s+lista\s+)?|a[ñn]ad[ei]r?\s+(?:a\s+la\s+lista\s+)?|falta(?:n)?\s+)\s*",
    re.IGNORECASE,
)
_RE_A_LA_LISTA = re.compile(r"\s+(?:a|en)\s+la\s+lista(?:\s+de\s+la\s+compra)?\s*$", re.IGNORECASE)


def es_para_la_lista(texto: str) -> bool:
    return bool(_RE_LISTA.match(texto or "")) or bool(_RE_A_LA_LISTA.search(texto or ""))


def articulos_de(texto: str) -> list[str]:
    """"comprar leche, huevos y pan" → ["Leche", "Huevos", "Pan"].

    Se parte por comas, saltos de línea y la "y" que separa la última. Lo
    repetido dentro del mismo mensaje entra una vez.
    """
    limpio = _RE_A_LA_LISTA.sub("", _RE_LISTA.sub("", texto or "", count=1)).strip().rstrip(".")
    trozos = re.split(r"\s*(?:,|;|\n|\s+y\s+|\s+e\s+)\s*", limpio)
    vistos, articulos = set(), []
    for t in trozos:
        t = t.strip(" .-·*")
        if not t:
            continue
        clave = sin_tildes(t)
        if clave in vistos:
            continue
        vistos.add(clave)
        articulos.append(t[:1].upper() + t[1:])
    return articulos


def _raiz(palabra: str) -> str:
    """Quita el plural: "tomates"/"tomate" y "limones"/"limón" son lo mismo.

    Se quita la "s" y luego una "e" final, así los dos plurales del español
    acaban en la misma raíz.
    """
    if len(palabra) > 3 and palabra.endswith("s"):
        palabra = palabra[:-1]
    if len(palabra) > 3 and palabra.endswith("e"):
        palabra = palabra[:-1]
    return palabra


def coincide(articulo: str, linea_ticket: str) -> bool:
    """Si una línea del ticket es ese artículo de la lista.

    El ticket escribe "LECHE ENTERA HACENDADO 6X1L" y la lista dice "Leche":
    vale con que todas las palabras de la lista (de 3 letras o más) estén en
    la línea. Al revés no: "Leche de avena" no se tacha con "LECHE ENTERA".
    """
    palabras = [_raiz(p) for p in re.findall(r"[a-zñ]{3,}", sin_tildes(articulo))]
    if not palabras:
        return False
    linea = {_raiz(p) for p in re.findall(r"[a-zñ]{3,}", sin_tildes(linea_ticket))}
    return all(p in linea for p in palabras)


# --- Efectivo y cartera -------------------------------------------------------

_RE_EFECTIVO = re.compile(r"\s*\b(?:en\s+)?(?:efectivo|met[aá]lico|cash|en\s+mano)\b\s*", re.I)
_RE_TARJETA = re.compile(r"\s*\b(?:con\s+|por\s+)?(?:tarjeta|bizum|transferencia|domiciliad[oa])\b\s*", re.I)


def forma_de_pago(texto: str) -> tuple[bool | None, str]:
    """"45 súper en efectivo" → (True, "45 súper"). Sin decirlo, None.

    Se quita la palabra del texto para que no acabe en el concepto.
    """
    if _RE_EFECTIVO.search(texto):
        return True, _RE_EFECTIVO.sub(" ", texto).strip()
    if _RE_TARJETA.search(texto):
        return False, _RE_TARJETA.sub(" ", texto).strip()
    return None, texto


_IMPORTE = r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?)?"
_RE_ENTRADA = re.compile(
    rf"^\s*(?:he\s+)?(?:saco|saqu[eé]|sacado|retiro|retir[eé]|cajero|meto|met[ií]|me\s+dieron|me\s+han\s+dado)"
    rf"\s+(?:de\s+)?{_IMPORTE}(?:\s+(?:del\s+cajero|en\s+la\s+cartera|a\s+la\s+cartera))?\s*\.?\s*$",
    re.I,
)
_RE_RECUENTO = re.compile(
    rf"^\s*(?:me\s+)?(?:quedan|queda|tengo|hay|cartera:?)\s+{_IMPORTE}(?:\s+en\s+la\s+cartera)?\s*\.?\s*$",
    re.I,
)


def interpretar_cartera(texto: str) -> tuple[str, Decimal] | None:
    """"saco 200" → ("entrada", 200); "me quedan 35" → ("recuento", 35).

    Tiene que ser la frase entera: "quedan 3 huevos" no es un recuento.
    """
    for tipo, patron in (("entrada", _RE_ENTRADA), ("recuento", _RE_RECUENTO)):
        m = patron.match(texto or "")
        if m:
            return tipo, Decimal(m.group(1).replace(",", "."))
    return None
