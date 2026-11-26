"""La copia de seguridad completa: todo lo de una persona en un ZIP.

La copia de antes era el CSV de los apuntes, y restaurarla devolvía los
cobros y gastos sueltos: sin sus trabajos, sin clientes, sin citas, sin
hábitos y sin nada de Casa. Los datos ya se han perdido dos veces; la tercera
no puede costar todo lo que no son apuntes.

El ZIP lleva dos cosas:
- `copia.json`, con todo y con los enlaces entre unas cosas y otras (qué
  gasto es de qué trabajo, qué cita de qué cliente). Es lo que se restaura.
- `apuntes.csv`, el CSV de siempre (utf-8 con BOM), para abrirlo en Excel
  sin herramientas. También vale, solo, para restaurar los apuntes.

Lo que NO va: las fotos y PDF de los tickets y facturas (pesan demasiado para
mandarlas cada domingo por Telegram) y los tokens de la web (son llaves: un
fichero reenviado por despiste no puede abrir la cuenta de nadie). De un
apunte con factura se guarda qué tipo de papel tenía, para que lo que iba a
la gestoría por su factura siga yendo.

Aquí solo se empaqueta, se desempaqueta y se valida: es regla pura, no toca
la base. Sacar los datos y volver a meterlos es de `servicios/copia_completa.py`.
Si una sola cosa está mal, no se lee nada, igual que la copia en CSV:
restaurar a medias sin saber qué se quedó fuera es peor que no restaurar.
"""
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal, InvalidOperation

from app.dominio.copia_csv import CopiaNoValida

FORMATO = "parte-del-dia"
VERSION = 1
NOMBRE_JSON = "copia.json"
NOMBRE_CSV = "apuntes.csv"

# Años de datos en JSON no llegan a unos pocos megas. El límite es para no
# descomprimir por error algo enorme que no es una copia.
TAMANO_MAXIMO_JSON = 50 * 1024 * 1024

_TIPOS_APUNTE = {"trabajo", "gasto", "nota"}
_TIPOS_CARTERA = {"entrada", "recuento"}
_PAPELES = {None, "ticket", "emitida"}


@dataclass
class CopiaCompleta:
    """La copia ya validada, con fechas, horas e importes de Python."""

    creada: date | None = None
    # De quién es: restaurar la copia de otra cuenta se avisa antes.
    user_id: int | None = None
    clientes: list[dict] = field(default_factory=list)
    trabajos: list[dict] = field(default_factory=list)
    apuntes: list[dict] = field(default_factory=list)
    citas: list[dict] = field(default_factory=list)
    habitos: list[dict] = field(default_factory=list)
    ajustes: dict | None = None
    emisores_propios: list[dict] = field(default_factory=list)
    casa: dict | None = None


# --- De Python a JSON -------------------------------------------------------


def a_texto(valor):
    """Fechas, horas e importes como texto; el resto tal cual."""
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def empaquetar(datos: dict, csv_apuntes: str) -> bytes:
    """El ZIP que se manda: el JSON con todo y el CSV para Excel."""
    contenido = {"formato": FORMATO, "version": VERSION, **datos}
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as zipeado:
        zipeado.writestr(
            NOMBRE_JSON, json.dumps(contenido, ensure_ascii=False, indent=1, default=a_texto)
        )
        zipeado.writestr(NOMBRE_CSV, csv_apuntes.encode("utf-8-sig"))
    return salida.getvalue()


# --- De JSON a Python -------------------------------------------------------


def _fecha(valor, opcional=False) -> date | None:
    if valor in (None, "") and opcional:
        return None
    try:
        return date.fromisoformat(str(valor))
    except ValueError as exc:
        raise ValueError(f"fecha '{valor}' no reconocida") from exc


def _hora(valor) -> time | None:
    if valor in (None, ""):
        return None
    try:
        return time.fromisoformat(str(valor))
    except ValueError as exc:
        raise ValueError(f"hora '{valor}' no reconocida") from exc


def _importe(valor) -> Decimal:
    try:
        importe = Decimal(str(valor))
    except InvalidOperation as exc:
        raise ValueError(f"importe '{valor}' no reconocido") from exc
    if not importe.is_finite() or importe < 0:
        raise ValueError(f"importe '{valor}' no válido")
    if importe.as_tuple().exponent < -2:
        raise ValueError(f"importe '{valor}' con más de dos decimales")
    return importe


def _texto(valor, obligatorio=False) -> str | None:
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obligatorio:
            raise ValueError("falta un texto obligatorio")
        return None
    if not isinstance(valor, str):
        raise ValueError(f"'{valor}' no es un texto")
    return valor


def _si_no(valor) -> bool:
    if not isinstance(valor, bool):
        raise ValueError(f"'{valor}' no es sí ni no")
    return valor


def _id(valor) -> int | None:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"'{valor}' no es un número de ficha")
    return valor


def _cliente(d: dict) -> dict:
    return {
        "id": _id(d.get("id")),
        "nombre": _texto(d.get("nombre"), obligatorio=True).strip(),
        "telefono": _texto(d.get("telefono")),
        "direccion": _texto(d.get("direccion")),
        "notas": _texto(d.get("notas")),
    }


def _trabajo(d: dict) -> dict:
    return {
        "id": _id(d.get("id")),
        "titulo": _texto(d.get("titulo"), obligatorio=True).strip(),
        "descripcion": _texto(d.get("descripcion")),
        "cliente_id": _id(d.get("cliente_id")),
        "fecha_inicio": _fecha(d.get("fecha_inicio"), opcional=True),
        "fecha_fin": _fecha(d.get("fecha_fin"), opcional=True),
        "facturado": _si_no(d.get("facturado", False)),
        "resena": _si_no(d.get("resena", False)),
    }


def _apunte(d: dict) -> dict:
    tipo = d.get("tipo")
    if tipo not in _TIPOS_APUNTE:
        raise ValueError(f"tipo '{tipo}' desconocido")
    papel = d.get("factura")
    if papel not in _PAPELES:
        raise ValueError(f"factura '{papel}' desconocida")
    return {
        "fecha": _fecha(d.get("fecha")),
        "tipo": tipo,
        "concepto": _texto(d.get("concepto"), obligatorio=True).strip(),
        "importe": _importe(d.get("importe")),
        "pendiente": _si_no(d.get("pendiente", False)),
        "hecha": _si_no(d.get("hecha", False)),
        "origen": _texto(d.get("origen")) or "copia",
        "cliente_id": _id(d.get("cliente_id")),
        "trabajo_id": _id(d.get("trabajo_id")),
        "para_gestoria": _si_no(d.get("para_gestoria", False)),
        "factura": papel,
    }


def _cita(d: dict) -> dict:
    return {
        "fecha": _fecha(d.get("fecha")),
        "fecha_fin": _fecha(d.get("fecha_fin"), opcional=True),
        "hora": _hora(d.get("hora")),
        "titulo": _texto(d.get("titulo"), obligatorio=True).strip(),
        "direccion": _texto(d.get("direccion")),
        "notas": _texto(d.get("notas")),
        "hecha": _si_no(d.get("hecha", False)),
        "cliente_id": _id(d.get("cliente_id")),
        "trabajo_id": _id(d.get("trabajo_id")),
        "avisada_el": _fecha(d.get("avisada_el"), opcional=True),
    }


def _habito(d: dict) -> dict:
    dias = _texto(d.get("dias"), obligatorio=True)
    if any(c not in "0123456" for c in dias):
        raise ValueError(f"días '{dias}' no válidos")
    hechos = d.get("hechos") or []
    if not isinstance(hechos, list):
        raise ValueError("los días hechos no son una lista")
    return {
        "nombre": _texto(d.get("nombre"), obligatorio=True).strip(),
        "dias": dias,
        "inicio": _fecha(d.get("inicio")),
        "recordar_a": _hora(d.get("recordar_a")),
        "hechos": sorted({_fecha(h) for h in hechos}),
    }


def _ajustes(d) -> dict | None:
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ValueError("los ajustes no son una ficha")
    return {
        "avisos_activos": _si_no(d.get("avisos_activos", True)),
        "correo": _texto(d.get("correo")),
    }


def _emisor(d: dict) -> dict:
    return {
        "nif": _texto(d.get("nif")),
        "nombre": _texto(d.get("nombre")),
        "iban": _texto(d.get("iban")),
    }


def _miembro(d: dict) -> dict:
    user_id = _id(d.get("user_id"))
    if user_id is None:
        raise ValueError("una persona sin número")
    return {
        "user_id": user_id,
        "nombre": _texto(d.get("nombre"), obligatorio=True).strip(),
        "titular": _si_no(d.get("titular", False)),
        "efectivo": _si_no(d.get("efectivo", True)),
    }


def _gasto_casa(d: dict) -> dict:
    return {
        "id": _id(d.get("id")),
        "user_id": _id(d.get("user_id")),
        "fecha": _fecha(d.get("fecha")),
        "concepto": _texto(d.get("concepto"), obligatorio=True).strip(),
        "importe": _importe(d.get("importe")),
        "categoria": _texto(d.get("categoria")) or "Otros",
        "origen": _texto(d.get("origen")) or "copia",
        "efectivo": _si_no(d.get("efectivo", False)),
    }


def _cartera(d: dict) -> dict:
    tipo = d.get("tipo")
    if tipo not in _TIPOS_CARTERA:
        raise ValueError(f"movimiento de cartera '{tipo}' desconocido")
    return {
        "user_id": _id(d.get("user_id")),
        "fecha": _fecha(d.get("fecha")),
        "tipo": tipo,
        "importe": _importe(d.get("importe")),
        "gasto_id": _id(d.get("gasto_id")),
        "hasta_gasto_id": _id(d.get("hasta_gasto_id")),
    }


def _articulo(d: dict) -> dict:
    return {
        "texto": _texto(d.get("texto"), obligatorio=True).strip(),
        "hay": _si_no(d.get("hay", False)),
        "anadido_por": _id(d.get("anadido_por")),
    }


def _lista(bruto: dict, seccion: str, leer, errores: list[str]) -> list[dict]:
    elementos = bruto.get(seccion) or []
    if not isinstance(elementos, list):
        errores.append(f"{seccion}: no es una lista")
        return []
    leidos = []
    for numero, elemento in enumerate(elementos, start=1):
        try:
            if not isinstance(elemento, dict):
                raise ValueError("no es una ficha")
            leidos.append(leer(elemento))
        except ValueError as exc:
            errores.append(f"{seccion} nº {numero}: {exc}")
    return leidos


def _casa(bruto, errores: list[str]) -> dict | None:
    if bruto is None:
        return None
    if not isinstance(bruto, dict):
        errores.append("casa: no es una ficha")
        return None
    return {
        "nombre": (_texto(bruto.get("nombre")) or "Casa").strip(),
        "miembros": _lista(bruto, "miembros", _miembro, errores),
        "gastos": _lista(bruto, "gastos", _gasto_casa, errores),
        "cartera": _lista(bruto, "cartera", _cartera, errores),
        "compra": _lista(bruto, "compra", _articulo, errores),
    }


def es_zip(datos: bytes) -> bool:
    return zipfile.is_zipfile(io.BytesIO(datos))


def desempaquetar(datos: bytes) -> dict:
    """El JSON de dentro del ZIP, sin validar todavía."""
    try:
        zipeado = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile as exc:
        raise CopiaNoValida("no es un ZIP") from exc
    with zipeado:
        try:
            info = zipeado.getinfo(NOMBRE_JSON)
        except KeyError as exc:
            raise CopiaNoValida(f"no lleva dentro {NOMBRE_JSON}: no es una de mis copias") from exc
        if info.file_size > TAMANO_MAXIMO_JSON:
            raise CopiaNoValida("es demasiado grande para ser una de mis copias")
        try:
            bruto = json.loads(zipeado.read(info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise CopiaNoValida("el contenido está dañado") from exc
    if not isinstance(bruto, dict) or bruto.get("formato") != FORMATO:
        raise CopiaNoValida("no es una de mis copias")
    version = bruto.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise CopiaNoValida("es de una versión más nueva de la app; actualízala antes de restaurar")
    return bruto


def leer(datos: bytes) -> CopiaCompleta:
    """El ZIP de una copia, validado entero. Una sola cosa mal y no se lee nada."""
    bruto = desempaquetar(datos)
    errores: list[str] = []
    copia = CopiaCompleta(
        clientes=_lista(bruto, "clientes", _cliente, errores),
        trabajos=_lista(bruto, "trabajos", _trabajo, errores),
        apuntes=_lista(bruto, "apuntes", _apunte, errores),
        citas=_lista(bruto, "citas", _cita, errores),
        habitos=_lista(bruto, "habitos", _habito, errores),
        emisores_propios=_lista(bruto, "emisores_propios", _emisor, errores),
        casa=_casa(bruto.get("casa"), errores),
    )
    try:
        copia.creada = _fecha(bruto.get("creada"), opcional=True)
        copia.user_id = _id(bruto.get("user_id"))
        copia.ajustes = _ajustes(bruto.get("ajustes"))
    except ValueError as exc:
        errores.append(str(exc))
    if errores:
        resto = f" (y {len(errores) - 3} más)" if len(errores) > 3 else ""
        raise CopiaNoValida("; ".join(errores[:3]) + resto)
    return copia
