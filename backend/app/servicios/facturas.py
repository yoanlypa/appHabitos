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
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.models import Apunte, EmisorPropio, Factura
from app.dominio.models import Cita, Cliente
from app.dominio.tickets import (
    DatosTicket,
    Propios,
    cruzada,
    descruzar,
    emisor_leido,
    es_factura_propia,
    fecha_escrita,
    interpretar_lectura,
    marca_cobrado,
    marca_propia,
    texto_de_vale,
)
from app.nucleo.config import NIF_PROPIO, NOMBRES_PROPIOS
from app.nucleo import archivos
from app.nucleo.lectura_tickets import leer_ticket
from app.nucleo.paginas_pdf import PdfNoLegible, unir_en_una
from app.nucleo.paginas_pdf import paginas as paginas_pdf
from app.nucleo.pdf import PaginaDeDatos, imagenes_a_pdf
from app.nucleo.tiempo import hoy_local
from app.dominio.gestoria import marca_gestoria
from app.servicios.apuntes import MovimientoNoValido, crear_nota, trabajo_de_gasto


def _propios(db: Session, user_id: int) -> Propios:
    """Lo de Railway (NIF_PROPIO, NOMBRES_PROPIOS) más lo aprendido de Yoa."""
    aprendidos = db.query(EmisorPropio).filter(EmisorPropio.user_id == user_id).all()
    return Propios(
        nifs=[NIF_PROPIO, *(e.nif for e in aprendidos if e.nif)],
        nombres=[*NOMBRES_PROPIOS, *(e.nombre for e in aprendidos if e.nombre)],
        ibans=[e.iban for e in aprendidos if e.iban],
    )


def _es_propia(db: Session, user_id: int, datos: DatosTicket) -> bool:
    return es_factura_propia(datos.detalle, datos.comercio, _propios(db, user_id))


def _enderezar(db: Session, user_id: int, factura: Factura, datos: DatosTicket) -> DatosTicket:
    """En una factura que es de Yoa, si la IA lo puso de cliente, se da la vuelta.

    Pasó con su factura a IG España XXI: la IA leyó a la empresa como emisor
    y a Yoa como cliente, y el trabajo quedó a nombre del propio Yoa. Se
    corrige también lo guardado, para que la ficha del PDF diga lo correcto.
    """
    if not cruzada(datos.detalle, datos.comercio, _propios(db, user_id)):
        return datos
    detalle, comercio = descruzar(datos.detalle, datos.comercio)
    datos = DatosTicket(
        total=datos.total, fecha=datos.fecha, comercio=comercio, iva=datos.iva,
        concepto=datos.concepto, detalle=detalle, esquinas=datos.esquinas,
    )
    factura.datos = json.dumps(_como_json(datos), ensure_ascii=False)
    db.flush()
    return datos


def aprender_emisor(db: Session, user_id: int, datos: DatosTicket) -> None:
    """Recuerda el emisor de una factura que Yoa ha dicho que es suya.

    Se llama con lo leído ya enderezado. Solo se guarda lo que aún no se
    sabía (así no se llena de repetidos), y nunca un NIF que también es el del
    destinatario: eso es una compra mal leída y enseñaría a tomar compras por
    facturas propias. Ni nada del emisor si quien sale de cliente es Yoa: es
    la lectura cruzada sin arreglar, y aprenderla haría "suyo" al cliente.
    """
    propios = _propios(db, user_id)
    if cruzada(datos.detalle, datos.comercio, propios):
        return
    nif, nombre, iban = emisor_leido(datos.detalle, datos.comercio)
    destinatario = datos.detalle.get("destinatario") or {}
    if nif and (propios.nif(nif) or emisor_leido({"cif": destinatario.get("nif")}, None)[0] == nif):
        nif = None
    if nombre and propios.nombre(nombre):
        nombre = None
    if iban and propios.iban(iban):
        iban = None
    if not (nif or nombre or iban):
        return
    db.add(EmisorPropio(user_id=user_id, nif=nif, nombre=nombre, iban=iban))
    db.flush()


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
    # Si no se leyó la fecha (ni se escribió con la foto) y se puso la de
    # hoy. Hay que decirlo: un gasto en el día que no es descuadra el mes.
    fecha_supuesta: bool = False
    # Si era una factura que emite Yoa: lo que se hizo con ella.
    emitida: "FacturaEmitida | None" = None


def guardar_factura(db: Session, user_id: int, imagen: bytes, mime: str) -> Factura:
    if not imagen:
        raise FacturaNoValida("la imagen llegó vacía")
    if len(imagen) > archivos.TAMANO_MAXIMO:
        raise FacturaNoValida("la imagen es demasiado grande (máximo 15 MB)")
    if mime not in archivos.EXTENSIONES:
        raise FacturaNoValida("solo se admiten fotos (JPG, PNG, WEBP, HEIC) o PDF")
    factura = Factura(
        user_id=user_id, ruta=archivos.guardar(imagen, mime), mime=mime, tamano=len(imagen)
    )
    db.add(factura)
    db.commit()
    db.refresh(factura)
    return factura


def _imagen_para_leer(contenido: bytes, mime: str) -> tuple[bytes, str]:
    """Lo que se le enseña a la IA: la foto tal cual, o las páginas del PDF.

    Una factura en PDF (la de la luz, la de un proveedor por email) se pinta
    página a página y se une en una sola imagen, porque el total o la fecha
    pueden estar en la segunda.
    """
    if mime != "application/pdf":
        return contenido, mime
    try:
        hoja = unir_en_una(paginas_pdf(contenido))
    except PdfNoLegible as exc:
        raise FacturaNoValida(str(exc)) from exc
    salida = io.BytesIO()
    hoja.save(salida, format="JPEG", quality=85)
    return salida.getvalue(), "image/jpeg"


def imagen_para_leer(contenido: bytes, mime: str) -> tuple[bytes, str]:
    """Lo mismo, para quien lee otra cosa que un ticket (una lista de pagos)."""
    return _imagen_para_leer(contenido, mime)


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
        leido = await leer_ticket(*_imagen_para_leer(imagen, mime))
    except Exception:
        borrar_factura(db, user_id, factura.id)
        raise
    datos = interpretar_lectura(leido, hoy_local())
    if mime == "application/pdf":
        datos.esquinas = None  # un PDF ya viene recto: no hay papel que enderezar
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
    trabajo_id: int | None = None,
    para_gestoria: bool = False,
) -> Apunte:
    """El gasto confirmado, con su foto colgada.

    Es el momento de decir de qué trabajo es o si va a la gestoría: se tiene
    el ticket delante. Después se puede cambiar, pero después no se hace.
    """
    factura = _suya(db, user_id, factura_id)
    if factura.apunte_id is not None:
        raise GastoNoValido("esta factura ya está anotada")
    if importe is None or importe <= 0:
        raise GastoNoValido("el importe tiene que ser mayor que cero")
    concepto = (concepto or "").strip() or "Ticket escaneado"
    if trabajo_id is not None:
        try:
            trabajo_de_gasto(db, user_id, trabajo_id)
        except MovimientoNoValido as exc:
            raise GastoNoValido(str(exc)) from exc

    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy_local(),
        tipo="gasto",
        concepto=concepto,
        importe=importe,
        pendiente=False,
        origen=origen,
        trabajo_id=trabajo_id,
        # De un trabajo, sigue a su trabajo; la marca a mano es solo del suelto.
        para_gestoria=para_gestoria and trabajo_id is None,
    )
    db.add(apunte)
    db.flush()
    factura.apunte_id = apunte.id
    db.commit()
    db.refresh(apunte)
    _anotar_vales(db, user_id, factura, origen)
    return apunte


def _anotar_vales(db: Session, user_id: int, factura: Factura, origen: str) -> list[Apunte]:
    """Cada cheque, cupón o vale del ticket va al buzón como nota pendiente.

    Un cheque de devolución de 25 € en un ticket de gasolinera es dinero, y
    en el bolsillo se pierde o caduca sin acordarse. Como nota sale en el
    buzón y en /notas, y se marca ✓ al gastarlo. Se hace al confirmar el
    gasto y no al escanear: lo escaneado y abandonado no deja notas sueltas.
    """
    d = datos_leidos(factura)
    return [
        crear_nota(db, user_id, texto_de_vale(vale, d.get("comercio")), origen)
        for vale in d.get("vales") or []
    ]


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
    forzada, concepto = marca_propia(concepto)
    if forzada or _es_propia(db, user_id, leido.datos):
        leido.datos = _enderezar(db, user_id, leido.factura, leido.datos)
        # Se aprende también si ya se reconoció: así se guarda su IBAN, que
        # es lo que la delata la próxima vez que la IA la lea cruzada.
        aprender_emisor(db, user_id, leido.datos)
        cobrada, concepto = marca_cobrado(concepto)
        fecha_escrita_, concepto = fecha_escrita(concepto, hoy_local())
        fecha = fecha_escrita_ or leido.datos.fecha
        leido.fecha_supuesta = fecha is None
        leido.emitida = registrar_emitida(
            db, user_id, leido.factura, leido.datos, cobrada, concepto.strip(), fecha, origen
        )
        return leido, leido.emitida.apunte
    # El texto de la foto puede empezar por la fecha ("15/10 material baño"):
    # manda sobre la leída, que quien la escribe tiene el ticket delante. Es
    # lo útil al subir tickets viejos borrosos.
    # Y puede llevar "para la gestoría": desde el bot no hay casilla que marcar.
    para_gestoria, concepto = marca_gestoria(concepto)
    fecha_escrita_, concepto = fecha_escrita(concepto, hoy_local())
    fecha = fecha_escrita_ or leido.datos.fecha
    leido.fecha_supuesta = fecha is None
    apunte = anotar_gasto(
        db,
        user_id,
        leido.factura.id,
        concepto.strip() or leido.datos.concepto_sugerido,
        leido.datos.total,
        fecha,
        origen,
        para_gestoria=para_gestoria,
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
    """"1234.5" → "1.234,50 €". Respeta los 3 decimales del precio de la gasolina."""
    if not texto:
        return ""
    numero = Decimal(texto)
    formato = ".3f" if numero != numero.quantize(Decimal("0.01")) else ".2f"
    entero, _, decimales = f"{numero:{formato}}".partition(".")
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
        ("Emisor" if factura.emitida else "Comercio", d.get("razon_social") or d.get("comercio")),
        ("Cliente", (d.get("destinatario") or {}).get("nombre") if factura.emitida else None),
        ("NIF cliente", (d.get("destinatario") or {}).get("nif") if factura.emitida else None),
        ("CIF", d.get("cif")),
        ("Dirección", d.get("direccion")),
        ("Nº factura/ticket", d.get("numero")),
        ("Fecha", fecha),
        ("Forma de pago", d.get("forma_pago")),
        ("Anotado como", apunte.concepto if apunte else None),
    ]
    if d.get("documento") == "devolucion":
        filas.append(("Tipo", "Devolución / abono"))
    for vale in d.get("vales") or []:
        filas.append(("Pendiente de usar", texto_de_vale(vale, None).removeprefix("🎟 ")))
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
    if d.get("retencion"):
        pie.append(("Retención IRPF", "-" + _euros(d["retencion"])))
    if factura.emitida and apunte is not None:
        filas.append(("Estado", "Pendiente de cobro" if apunte.pendiente else "Cobrada"))
    return PaginaDeDatos(
        titulo="Factura emitida" if factura.emitida else "Datos del ticket",
        filas=[(e, v) for e, v in filas if v],
        cabecera=["Descripción", "Cant.", "Precio", "Importe"] if tabla else None,
        tabla=tabla or None,
        pie=pie or None,
    )


def pdf_del_periodo(
    db: Session,
    user_id: int,
    desde: date,
    hasta: date,
    emitidas: bool = False,
    solo_gestoria: bool = False,
) -> bytes | None:
    """Los justificantes entre dos fechas, uno por página.

    Con `solo_gestoria`, solo los de apuntes que van a la gestoría: los
    tickets de un trabajo que factura otra empresa no son para ella.

    Por separado los tickets de compra (gastos) y las facturas que emite Yoa
    (`emitidas`): la gestoría los pide aparte, porque unos son IVA soportado
    y otros IVA repercutido. Por fecha del apunte, que es el orden en que
    los piden. Sin ninguno devuelve None, que no es un error.
    """
    facturas = (
        db.query(Factura)
        .join(Apunte, Factura.apunte_id == Apunte.id)
        .filter(
            Factura.user_id == user_id,
            Factura.emitida.is_(emitidas),
            Apunte.fecha >= desde,
            Apunte.fecha <= hasta,
        )
        .order_by(Apunte.fecha, Apunte.id)
        .all()
    )
    # Solo las fotos, sin la ficha de cada una: para la gestoría importa el
    # documento, y doblar las páginas del mes no aporta.
    if solo_gestoria:
        facturas = [f for f in facturas if f.apunte.gestoria]
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


@dataclass
class FechaCorregida:
    apunte: Apunte
    antes: date


@dataclass
class Relectura:
    corregidas: list
    sin_fecha: int  # releídos en los que tampoco se encontró la fecha
    quedan: int  # pendientes para otra tanda


def _sin_fecha_leida(factura: Factura) -> bool:
    """Sin la clave "fecha": nunca se leyó bien. Con fecha null: ya se releyó
    y tampoco salía, y no tiene sentido pagar otra vez por lo mismo."""
    return "fecha" not in datos_leidos(factura)


async def releer_fechas(db: Session, user_id: int, tanda: int = 25) -> Relectura:
    """Vuelve a leer los tickets cuya fecha no se entendió y los pone en su día.

    Existe por un fallo real: la fecha "24/10/2026" (como la escriben los
    tickets) se descartaba por no venir como "2026-10-24", y casi todo lo
    subido cayó en el día en que se subió. Las fotos están guardadas, así que
    se pueden releer: unas décimas de céntimo por ticket.

    Solo toca los que no tienen fecha leída, y solo cambia el día si ahora la
    encuentra: si no, el apunte se queda como estaba. No vuelve a crear las
    notas de los vales, que si ya se crearon saldrían repetidas. Va por
    tandas para que una lista larga no deje el bot colgado minutos.
    """
    candidatas = [
        f
        for f in db.query(Factura)
        .filter(Factura.user_id == user_id, Factura.apunte_id.isnot(None))
        .order_by(Factura.id)
        .all()
        if _sin_fecha_leida(f) and archivos.ruta_absoluta(f.ruta).exists()
    ]
    corregidas, sin_fecha = [], 0
    for factura in candidatas[:tanda]:
        contenido = archivos.ruta_absoluta(factura.ruta).read_bytes()
        try:
            para_leer = _imagen_para_leer(contenido, factura.mime)
        except FacturaNoValida:
            continue
        datos = interpretar_lectura(await leer_ticket(*para_leer), hoy_local())
        # Se guarda lo leído aunque no haya fecha: así no se vuelve a pedir.
        nuevos = _como_json(datos)
        nuevos.setdefault("fecha", None)
        factura.datos = json.dumps(nuevos, ensure_ascii=False)
        if datos.esquinas and not factura.esquinas:
            factura.esquinas = json.dumps(datos.esquinas)
        apunte = factura.apunte
        if datos.fecha is None:
            sin_fecha += 1
        elif datos.fecha != apunte.fecha:
            corregidas.append(FechaCorregida(apunte=apunte, antes=apunte.fecha))
            apunte.fecha = datos.fecha
        db.commit()
    return Relectura(
        corregidas=corregidas, sin_fecha=sin_fecha, quedan=max(0, len(candidatas) - tanda)
    )



# ---------- Facturas que emite Yoa ----------


@dataclass
class FacturaEmitida:
    """Lo que pasó con una factura de Yoa a un cliente.

    `apunte` es el trabajo del que cuelga. Si hay varios trabajos pendientes
    que podrían ser el suyo, `apunte` va vacío y `candidatos` dice entre
    cuáles elegir: colgarla del que no es descuadraría dos cuentas.
    """

    factura: Factura
    apunte: Apunte | None
    cliente: Cliente | None
    cliente_nuevo: bool
    vinculada: bool  # colgada de un trabajo que ya estaba anotado
    cobrada: bool
    candidatos: list = field(default_factory=list)


def importe_a_cobrar(datos: DatosTicket) -> Decimal | None:
    """Lo que de verdad entra: el total menos la retención de IRPF, si la hay."""
    if datos.total is None:
        return None
    retencion = Decimal(datos.detalle["retencion"]) if datos.detalle.get("retencion") else Decimal("0")
    return datos.total - retencion if retencion < datos.total else datos.total


def buscar_cliente(db: Session, user_id: int, destinatario: dict | None) -> Cliente | None:
    """El cliente ya dado de alta que es el destinatario: por NIF o por nombre exacto."""
    if not destinatario or not destinatario.get("nombre"):
        return None
    nif = destinatario.get("nif")
    nombre = destinatario["nombre"].casefold()
    for cliente in db.query(Cliente).filter(Cliente.user_id == user_id).all():
        if nif and nif in (cliente.notas or "").upper().replace(" ", "").replace("-", ""):
            return cliente
        if cliente.nombre.casefold() == nombre:
            return cliente
    return None


@dataclass
class VistaEmitida:
    """Lo que la web enseña antes de anotar una factura propia (sin tocar nada)."""

    cliente: str | None
    candidatos: list


def vista_emitida(db: Session, user_id: int, datos: DatosTicket) -> VistaEmitida | None:
    if not _es_propia(db, user_id, datos):
        return None
    if cruzada(datos.detalle, datos.comercio, _propios(db, user_id)):
        detalle, _ = descruzar(datos.detalle, datos.comercio)
        destinatario = detalle.get("destinatario")
    else:
        destinatario = datos.detalle.get("destinatario")
    cliente = buscar_cliente(db, user_id, destinatario)
    candidatos = (
        _trabajos_candidatos(db, user_id, cliente, {importe_a_cobrar(datos), datos.total})
        if cliente is not None
        else []
    )
    return VistaEmitida(cliente=(destinatario or {}).get("nombre"), candidatos=candidatos)


def anotar_emitida(
    db: Session,
    user_id: int,
    factura_id: int,
    apunte_id: int | None,
    cobrada: bool,
    concepto: str,
    importe: Decimal,
    fecha: date | None,
    origen: str,
) -> Apunte:
    """La factura propia confirmada desde la web: a un trabajo existente o a uno nuevo."""
    factura = _suya(db, user_id, factura_id)
    factura.emitida = True
    db.commit()
    if apunte_id is not None:
        return vincular_emitida(db, user_id, factura_id, apunte_id, cobrada)
    if factura.apunte_id is not None:
        raise GastoNoValido("esta factura ya está anotada")
    if importe is None or importe <= 0:
        raise GastoNoValido("el importe tiene que ser mayor que cero")
    datos = interpretar_lectura(datos_leidos(factura), hoy_local())
    datos = _enderezar(db, user_id, factura, datos)
    cliente, _ = _cliente_de(db, user_id, datos.detalle.get("destinatario"))
    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or datos.fecha or hoy_local(),
        tipo="trabajo",
        concepto=(concepto or "").strip() or _concepto_de_factura(datos, cliente, ""),
        importe=importe,
        pendiente=not cobrada,
        origen=origen,
        cliente_id=cliente.id if cliente else None,
        # Lleva colgada una factura de Yoa: está facturado, y va a la gestoría.
        facturado=True,
    )
    db.add(apunte)
    db.flush()
    factura.apunte_id = apunte.id
    db.commit()
    db.refresh(apunte)
    return apunte


def _cliente_de(db: Session, user_id: int, destinatario: dict | None) -> tuple[Cliente | None, bool]:
    """El cliente de la factura: el que ya existe con ese NIF o nombre, o uno nuevo.

    Aquí sí se da de alta solo, al revés que al anotar un texto: en una
    factura el nombre, el NIF y la dirección vienen escritos, no se adivinan.
    """
    if not destinatario or not destinatario.get("nombre"):
        return None, False
    existente = buscar_cliente(db, user_id, destinatario)
    if existente is not None:
        return existente, False
    nif = destinatario.get("nif")
    cliente = Cliente(
        user_id=user_id,
        nombre=destinatario["nombre"],
        telefono=destinatario.get("telefono"),
        direccion=destinatario.get("direccion"),
        notas=f"NIF: {nif}" if nif else None,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente, True


def _trabajos_candidatos(
    db: Session, user_id: int, cliente: Cliente | None, importes: set
) -> list[Apunte]:
    """Trabajos pendientes, sin factura, que podrían ser el de esta factura."""
    consulta = db.query(Apunte).filter(
        Apunte.user_id == user_id,
        Apunte.tipo == "trabajo",
        Apunte.pendiente.is_(True),
    )
    if cliente is not None:
        consulta = consulta.filter(Apunte.cliente_id == cliente.id)
    return [a for a in consulta.order_by(Apunte.fecha.desc()).all() if a.factura is None and a.importe in importes]


def registrar_emitida(
    db: Session,
    user_id: int,
    factura: Factura,
    datos: DatosTicket,
    cobrada: bool,
    concepto: str,
    fecha: date | None,
    origen: str,
) -> FacturaEmitida:
    """Una factura de Yoa: un trabajo pendiente de cobro con la factura colgada.

    Si ya hay un trabajo pendiente del mismo cliente por ese importe (se
    apuntó "Reforma baño Ana 980" antes de hacer la factura), se cuelga de
    ese en vez de crear otro: dos trabajos por lo mismo contarían doble lo
    cobrado. Si hay más de uno posible, no se elige: se devuelven para
    preguntar.
    """
    factura.emitida = True
    db.commit()
    cliente, nuevo = _cliente_de(db, user_id, datos.detalle.get("destinatario"))
    importe = importe_a_cobrar(datos)
    candidatos = [] if nuevo else _trabajos_candidatos(db, user_id, cliente, {importe, datos.total})
    resultado = FacturaEmitida(
        factura=factura, apunte=None, cliente=cliente, cliente_nuevo=nuevo,
        vinculada=False, cobrada=cobrada,
    )
    if len(candidatos) > 1:
        resultado.candidatos = candidatos
        return resultado
    if len(candidatos) == 1:
        resultado.apunte = vincular_emitida(db, user_id, factura.id, candidatos[0].id, cobrada)
        resultado.vinculada = True
        return resultado
    resultado.apunte = _nuevo_trabajo(
        db, user_id, factura, datos, cliente, importe, cobrada, concepto, fecha, origen
    )
    return resultado


def _concepto_de_factura(datos: DatosTicket, cliente: Cliente | None, escrito: str) -> str:
    partes = []
    if datos.detalle.get("numero"):
        partes.append(f"Fra. {datos.detalle['numero']}")
    partes.append(escrito or datos.concepto or "Factura")
    if cliente is not None:
        partes.append(cliente.nombre)
    return " · ".join(partes)


def _nuevo_trabajo(db, user_id, factura, datos, cliente, importe, cobrada, concepto, fecha, origen) -> Apunte:
    apunte = Apunte(
        user_id=user_id,
        fecha=fecha or hoy_local(),
        tipo="trabajo",
        concepto=_concepto_de_factura(datos, cliente, concepto),
        importe=importe,
        pendiente=not cobrada,
        origen=origen,
        cliente_id=cliente.id if cliente else None,
        # Lleva colgada una factura de Yoa: está facturado, y va a la gestoría.
        facturado=True,
    )
    db.add(apunte)
    db.flush()
    factura.apunte_id = apunte.id
    db.commit()
    db.refresh(apunte)
    return apunte


def vincular_emitida(
    db: Session, user_id: int, factura_id: int, apunte_id: int | None, cobrada: bool
) -> Apunte:
    """Cuelga una factura propia de un trabajo ya anotado, o crea uno (apunte_id None).

    Es lo que contesta la pregunta "¿de qué trabajo es esta factura?".
    """
    factura = _suya(db, user_id, factura_id)
    if factura.apunte_id is not None:
        raise GastoNoValido("esta factura ya está anotada")
    if apunte_id is None:
        datos = interpretar_lectura(datos_leidos(factura), hoy_local())
        cliente, _ = _cliente_de(db, user_id, datos.detalle.get("destinatario"))
        return _nuevo_trabajo(
            db, user_id, factura, datos, cliente, importe_a_cobrar(datos), cobrada, "", datos.fecha, "bot"
        )
    apunte = (
        db.query(Apunte)
        .filter(Apunte.id == apunte_id, Apunte.user_id == user_id, Apunte.tipo == "trabajo")
        .first()
    )
    if apunte is None or apunte.factura is not None:
        raise GastoNoValido("ese trabajo no existe o ya tiene factura")
    factura.apunte_id = apunte.id
    apunte.facturado = True
    if cobrada:
        apunte.pendiente = False
    db.commit()
    db.refresh(apunte)
    return apunte



def convertir_en_emitida(db: Session, user_id: int, apunte_id: int, cobrada: bool) -> Apunte:
    """Un gasto que en realidad era una factura de Yoa pasa a trabajo pendiente.

    Para cuando no se reconoció al subirla (pasó con una factura a nombre de
    Yoa como autónomo, no de la marca). Usa lo ya leído: no paga otra lectura.
    Sobre una que ya es suya, la repara: vuelve a mirar quién es el cliente
    (por si la IA la leyó cruzada) y rehace el concepto. Así se arregla lo
    que entró a nombre del propio Yoa.
    """
    apunte = (
        db.query(Apunte).filter(Apunte.id == apunte_id, Apunte.user_id == user_id).first()
    )
    if apunte is None:
        raise FacturaNoEncontrada(f"apunte {apunte_id} no existe")
    factura = apunte.factura
    if factura is None:
        raise GastoNoValido("ese apunte no tiene factura colgada")
    ya_era = factura.emitida
    datos = interpretar_lectura(datos_leidos(factura), hoy_local())
    datos = _enderezar(db, user_id, factura, datos)
    aprender_emisor(db, user_id, datos)
    cliente, _ = _cliente_de(db, user_id, datos.detalle.get("destinatario"))
    anterior = apunte.cliente
    factura.emitida = True
    apunte.tipo = "trabajo"
    apunte.facturado = True
    # Era un gasto: lo que tuviera de gasto ya no aplica.
    apunte.trabajo_id = None
    apunte.para_gestoria = False
    if not ya_era or cobrada:
        apunte.pendiente = not cobrada
    apunte.cliente_id = cliente.id if cliente else apunte.cliente_id
    apunte.concepto = _concepto_de_factura(datos, cliente, "")
    importe = importe_a_cobrar(datos)
    if importe:
        apunte.importe = importe
    db.flush()
    if anterior is not None and anterior.id != apunte.cliente_id:
        _borrar_si_soy_yo(db, user_id, anterior)
    db.commit()
    db.refresh(apunte)
    return apunte


def reparar_emitidas(db: Session, user_id: int) -> list[Apunte]:
    """Repasa todas las facturas propias ya anotadas y devuelve las que cambiaron.

    Para lo que entró antes del arreglo de las lecturas cruzadas: trabajos a
    nombre del propio Yoa. No paga ninguna lectura y no toca si están cobradas.
    """
    cambiadas = []
    emitidas = (
        db.query(Factura)
        .filter(Factura.user_id == user_id, Factura.emitida.is_(True), Factura.apunte_id.isnot(None))
        .all()
    )
    for factura in emitidas:
        antes = (factura.apunte.cliente_id, factura.apunte.concepto)
        apunte = convertir_en_emitida(db, user_id, factura.apunte_id, cobrada=False)
        if (apunte.cliente_id, apunte.concepto) != antes:
            cambiadas.append(apunte)
    return cambiadas


def _borrar_si_soy_yo(db: Session, user_id: int, cliente: Cliente) -> None:
    """El "cliente" que se dio de alta con los datos de Yoa, si no le queda nada.

    Sale de una lectura cruzada. Solo se borra si es él (por NIF o nombre) y
    ya no tiene apuntes ni citas: un cliente con historia no se toca solo.
    """
    propios = _propios(db, user_id)
    nif = (cliente.notas or "").removeprefix("NIF:").strip()
    if not (propios.nombre(cliente.nombre) or propios.nif(nif)):
        return
    if db.query(Apunte).filter(Apunte.cliente_id == cliente.id).count():
        return
    if db.query(Cita).filter(Cita.cliente_id == cliente.id).count():
        return
    db.delete(cliente)
