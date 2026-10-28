"""Casos de uso del escáner de tickets: leer la foto y anotarla como gasto.

Son dos pasos a propósito, y los dos viven aquí para que la web y el bot
hagan lo mismo:

1. `escanear()` guarda la foto y devuelve lo leído, sin anotar nada. La web
   lo enseña en un formulario ya relleno para que se confirme o corrija: si
   el modelo leyó 234,00 donde ponía 23,40, se ve antes de que entre en las
   cuentas.
2. `anotar_gasto()` crea el gasto con lo confirmado y le cuelga la foto.

El bot hace los dos seguidos (no hay formulario en Telegram) y responde con
lo que entendió, igual que con las notas de voz: si está mal, se /borra.

Lo escaneado y nunca confirmado se queda huérfano; `limpiar_huerfanas()` lo
borra pasado un día (se llama al escanear) para que no se acumulen fotos que nadie va a usar.
"""
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte, Factura
from app.dominio.tickets import DatosTicket, interpretar_lectura
from app.nucleo import archivos
from app.nucleo.lectura_tickets import leer_ticket
from app.nucleo.pdf import PaginaDeDatos, imagenes_a_pdf
from app.nucleo.tiempo import hoy_local


class FacturaNoEncontrada(LookupError):
    """No existe esa factura para ese usuario."""


class FacturaNoValida(ValueError):
    """La imagen no se puede guardar (vacía, enorme o de un tipo raro)."""


class GastoNoValido(ValueError):
    """Lo que se quiere anotar no es un gasto que se pueda guardar."""


@dataclass
class TicketEscaneado:
    factura: Factura
    datos: DatosTicket


def guardar_factura(db: Session, user_id: int, imagen: bytes, mime: str) -> Factura:
    if not imagen:
        raise FacturaNoValida("la imagen llegó vacía")
    if len(imagen) > archivos.TAMANO_MAXIMO:
        raise FacturaNoValida("la imagen es demasiado grande (máximo 15 MB)")
    if mime not in archivos.EXTENSIONES:
        raise FacturaNoValida("solo se admiten fotos JPG, PNG, WEBP o HEIC")
    factura = Factura(
        user_id=user_id, ruta=archivos.guardar(imagen, mime), mime=mime, tamano=len(imagen)
    )
    db.add(factura)
    db.commit()
    db.refresh(factura)
    return factura


async def escanear(db: Session, user_id: int, imagen: bytes, mime: str) -> TicketEscaneado:
    """Guarda la foto y la lee. Si la lectura falla, la foto no se queda.

    Se lee antes de guardar en la base para no dejar una fila por cada
    intento fallido; el fichero sí se escribe primero, porque si leer va
    bien y guardar falla después, perder la foto sería lo peor.
    """
    # Barrer aquí lo abandonado evita una tarea programada más: si nadie
    # escanea, tampoco se acumula nada nuevo.
    limpiar_huerfanas(db)
    factura = guardar_factura(db, user_id, imagen, mime)
    try:
        leido = await leer_ticket(imagen, mime)
    except Exception:
        borrar_factura(db, user_id, factura.id)
        raise
    datos = interpretar_lectura(leido, hoy_local())
    # Se guarda todo lo leído, no solo lo que va al gasto: el CIF, las líneas
    # y la base imponible son lo que pide la gestoría, y volver a leer la foto
    # costaría otra llamada.
    factura.datos = json.dumps(_como_json(datos), ensure_ascii=False)
    factura.esquinas = json.dumps(datos.esquinas) if datos.esquinas else None
    db.commit()
    return TicketEscaneado(factura=factura, datos=datos)


def _como_json(datos: DatosTicket) -> dict:
    principal = {
        "comercio": datos.comercio,
        "concepto": datos.concepto,
        "fecha": datos.fecha.isoformat() if datos.fecha else None,
        "total": f"{datos.total:.2f}" if datos.total is not None else None,
        "iva": f"{datos.iva:.2f}" if datos.iva is not None else None,
    }
    return {**{k: v for k, v in principal.items() if v is not None}, **datos.detalle}


def datos_leidos(factura: Factura) -> dict:
    """Lo que se leyó del ticket, o vacío para lo escaneado antes de guardarlo."""
    try:
        return json.loads(factura.datos) if factura.datos else {}
    except ValueError:
        return {}


def _esquinas_de(factura: Factura) -> list | None:
    try:
        return json.loads(factura.esquinas) if factura.esquinas else None
    except ValueError:
        return None


def _suya(db: Session, user_id: int, factura_id: int) -> Factura:
    factura = (
        db.query(Factura)
        .filter(Factura.id == factura_id, Factura.user_id == user_id)
        .first()
    )
    if factura is None:
        raise FacturaNoEncontrada(f"factura {factura_id} no existe para el usuario {user_id}")
    return factura


def anotar_gasto(
    db: Session,
    user_id: int,
    factura_id: int,
    concepto: str,
    importe: Decimal,
    fecha: date | None,
    origen: str,
) -> Apunte:
    """El gasto confirmado, con su foto colgada."""
    factura = _suya(db, user_id, factura_id)
    if factura.apunte_id is not None:
        raise GastoNoValido("esta factura ya está anotada")
    if importe is None or importe <= 0:
        raise GastoNoValido("el importe tiene que ser mayor que cero")
    concepto = (concepto or "").strip() or "Ticket escaneado"

    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy_local(),
        tipo="gasto",
        concepto=concepto,
        importe=importe,
        pendiente=False,
        origen=origen,
    )
    db.add(apunte)
    db.flush()
    factura.apunte_id = apunte.id
    db.commit()
    db.refresh(apunte)
    return apunte


def ruta_de(db: Session, user_id: int, factura_id: int):
    """El fichero y su tipo, para servirlo. Solo al dueño."""
    factura = _suya(db, user_id, factura_id)
    return archivos.ruta_absoluta(factura.ruta), factura.mime


def borrar_factura(db: Session, user_id: int, factura_id: int) -> None:
    factura = _suya(db, user_id, factura_id)
    archivos.borrar(factura.ruta)
    db.delete(factura)
    db.commit()


def limpiar_huerfanas(db: Session, horas: int = 24) -> int:
    """Borra lo escaneado y nunca anotado. Devuelve cuántas se fueron."""
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    huerfanas = (
        db.query(Factura)
        .filter(Factura.apunte_id.is_(None), Factura.creado < limite)
        .all()
    )
    for factura in huerfanas:
        archivos.borrar(factura.ruta)
        db.delete(factura)
    db.commit()
    return len(huerfanas)


async def escanear_y_anotar(
    db: Session, user_id: int, imagen: bytes, mime: str, concepto: str | None, origen: str
) -> tuple[TicketEscaneado, Apunte | None]:
    """Los dos pasos seguidos, para el bot. Sin total leído no se anota nada.

    Un gasto de 0 € no sirve y uno inventado es peor; en ese caso la foto se
    borra y quien la mandó lo sabe en el momento.
    """
    leido = await escanear(db, user_id, imagen, mime)
    if leido.datos.total is None:
        borrar_factura(db, user_id, leido.factura.id)
        return leido, None
    apunte = anotar_gasto(
        db,
        user_id,
        leido.factura.id,
        (concepto or "").strip() or leido.datos.concepto_sugerido,
        leido.datos.total,
        leido.datos.fecha,
        origen,
    )
    return leido, apunte


def pdf_de_factura(db: Session, user_id: int, factura_id: int) -> tuple[bytes, str]:
    """El ticket como PDF escaneado, con un nombre que diga qué es."""
    factura = _suya(db, user_id, factura_id)
    contenido = imagenes_a_pdf(
        [archivos.ruta_absoluta(factura.ruta)],
        esquinas=[_esquinas_de(factura)],
        datos=[_pagina_de_datos(factura)],
    )
    return contenido, _nombre_pdf(factura)


def _euros(texto: str | None) -> str:
    if not texto:
        return ""
    entero, _, decimales = f"{Decimal(texto):.2f}".partition(".")
    signo = "-" if entero.startswith("-") else ""
    entero = entero.lstrip("-")
    miles = ".".join(entero[max(0, i - 3):i] for i in range(len(entero), 0, -3)[::-1])
    return f"{signo}{miles},{decimales} €"


def _pagina_de_datos(factura: Factura) -> PaginaDeDatos | None:
    """La ficha del ticket pasada a limpio, detrás de la foto.

    Sin datos leídos (lo escaneado antes de que se guardaran) no hay página:
    una ficha vacía no aporta nada.
    """
    d = datos_leidos(factura)
    if not d:
        return None
    apunte = factura.apunte
    fecha = d.get("fecha") or (apunte.fecha.isoformat() if apunte else None)
    if fecha:
        a, m, dia = fecha.split("-")
        fecha = f"{dia}/{m}/{a}" + (f"  {d['hora']}" if d.get("hora") else "")
    filas = [
        ("Comercio", d.get("razon_social") or d.get("comercio")),
        ("CIF", d.get("cif")),
        ("Dirección", d.get("direccion")),
        ("Nº factura/ticket", d.get("numero")),
        ("Fecha", fecha),
        ("Forma de pago", d.get("forma_pago")),
        ("Anotado como", apunte.concepto if apunte else None),
    ]
    if d.get("documento") == "devolucion":
        filas.append(("Tipo", "Devolución / abono"))
    lineas = d.get("lineas") or []
    tabla = [
        [l["descripcion"], (l.get("cantidad") or "").replace(".", ","),
         _euros(l.get("precio_unitario")), _euros(l.get("importe"))]
        for l in lineas
    ]
    pie = []
    if d.get("descuento"):
        pie.append(("Descuentos", "-" + _euros(d["descuento"])))
    if d.get("base_imponible"):
        pie.append(("Base imponible", _euros(d["base_imponible"])))
    for tipo in d.get("tipos_iva") or []:
        if tipo.get("cuota"):
            pie.append((f"IVA {tipo['tipo'].replace('.', ',')} %", _euros(tipo["cuota"])))
    if d.get("iva") and not d.get("tipos_iva"):
        pie.append(("IVA", _euros(d["iva"])))
    total = d.get("total") or (f"{apunte.importe:.2f}" if apunte else None)
    if total:
        pie.append(("TOTAL", _euros(total)))
    return PaginaDeDatos(
        titulo="Datos del ticket",
        filas=[(e, v) for e, v in filas if v],
        cabecera=["Descripción", "Cant.", "Precio", "Importe"] if tabla else None,
        tabla=tabla or None,
        pie=pie or None,
    )


def pdf_del_periodo(db: Session, user_id: int, desde: date, hasta: date) -> bytes | None:
    """Todas las facturas de los gastos entre dos fechas, una por página.

    Por fecha del gasto y no de escaneo: es el orden en que las pide la
    gestoría. Sin facturas devuelve None, que no es un error.
    """
    facturas = (
        db.query(Factura)
        .join(Apunte, Factura.apunte_id == Apunte.id)
        .filter(
            Factura.user_id == user_id,
            Apunte.fecha >= desde,
            Apunte.fecha <= hasta,
        )
        .order_by(Apunte.fecha, Apunte.id)
        .all()
    )
    # Solo las fotos, sin la ficha de cada una: para la gestoría importa el
    # documento, y doblar las páginas del mes no aporta.
    presentes = [f for f in facturas if archivos.ruta_absoluta(f.ruta).exists()]
    if not presentes:
        return None
    return imagenes_a_pdf(
        [archivos.ruta_absoluta(f.ruta) for f in presentes],
        esquinas=[_esquinas_de(f) for f in presentes],
    )


def _nombre_pdf(factura: Factura) -> str:
    if factura.apunte is None:
        return f"ticket-{factura.id}.pdf"
    apunte = factura.apunte
    concepto = "".join(c if c.isalnum() else "-" for c in apunte.concepto.lower())
    concepto = "-".join(p for p in concepto.split("-") if p)[:40]
    return f"{apunte.fecha.isoformat()}-{concepto or 'ticket'}.pdf"
