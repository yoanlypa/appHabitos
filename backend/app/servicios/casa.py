"""Casos de uso de Casa: la casa compartida, sus gastos y su lista de la compra.

Yoa quería llevar el dinero de casa aparte del negocio y que su esposa
también pudiera ir anotando lo que gasta. Por eso:

- **Todo es de la casa, no de una persona.** Cualquiera de la casa ve, anota,
  corrige y borra; cada gasto guarda quién lo pagó para el reparto del mes.
- **El titular es quien la crea**, sin hacer nada: la primera vez que Yoa
  usa Casa, la casa aparece. Los demás entran con un código de invitación
  (por el bot con /unirme o por un enlace de la web) y solo ven Casa.
- **Nada de esto toca el negocio**: tablas propias, y ningún resumen, ni el
  trimestre, ni la gestoría los leen.
- **La lista y la despensa son la misma fila** (`ArticuloCompra.hay`): se
  compra y pasa a "en casa"; se acaba y vuelve a la lista. Lo que hay en casa
  es lo que se le da al modelo para pensar qué hacer de comer.
"""
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.dominio import casa as reglas
from app.dominio.models import ArticuloCompra, GastoCasa, Hogar, InvitacionHogar, MiembroHogar
from app.nucleo import recetas as cocina
from app.nucleo.tiempo import hoy_local
from app.servicios.auth import generar_token


class SinCasa(LookupError):
    """Esa persona no es de ninguna casa (y no puede crearla: no es titular)."""


class NoEncontrado(LookupError):
    """No existe en tu casa."""


class InvitacionNoValida(ValueError):
    """El código no existe, ya se usó o ha caducado."""


class YaEnOtraCasa(ValueError):
    """Quien quiere entrar ya comparte otra casa con alguien."""


class DatoNoValido(ValueError):
    """Un gasto sin concepto, un importe <= 0, una fecha futura..."""


class SoloTitular(PermissionError):
    """Eso solo lo puede hacer quien creó la casa."""


DIAS_INVITACION = 7
# Sin letras que se confundan al dictarlas o copiarlas (0/O, 1/I/L).
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


# --- La casa y quién vive en ella ------------------------------------------


def miembro_de(db: Session, user_id: int) -> MiembroHogar | None:
    return db.query(MiembroHogar).filter(MiembroHogar.user_id == user_id).first()


def asegurar_casa(db: Session, user_id: int, nombre: str = "Yo") -> MiembroHogar:
    """La casa de esa persona; si no tiene, se crea con ella de titular."""
    miembro = miembro_de(db, user_id)
    if miembro:
        # Entró primero por la web (sin nombre) y ahora llega por Telegram:
        # se queda con su nombre de verdad en vez de "Yo".
        if miembro.nombre == "Yo" and nombre and nombre.strip() not in ("", "Yo"):
            miembro.nombre = nombre.strip()[:40]
            db.commit()
        return miembro
    hogar = Hogar(nombre="Casa")
    db.add(hogar)
    db.flush()
    miembro = MiembroHogar(hogar_id=hogar.id, user_id=user_id, nombre=(nombre or "Yo").strip()[:40], titular=True)
    db.add(miembro)
    db.commit()
    db.refresh(miembro)
    return miembro


def _miembro(db: Session, user_id: int) -> MiembroHogar:
    miembro = miembro_de(db, user_id)
    if not miembro:
        raise SinCasa("no eres de ninguna casa")
    return miembro


def solo_casa(db: Session, user_id: int) -> bool:
    """Si esa persona solo debe ver Casa: es de una casa y no es su titular."""
    miembro = miembro_de(db, user_id)
    return bool(miembro and not miembro.titular)


def miembros(db: Session, hogar_id: int) -> list[MiembroHogar]:
    return db.query(MiembroHogar).filter(MiembroHogar.hogar_id == hogar_id).order_by(MiembroHogar.id).all()


def cambiar_nombre(db: Session, user_id: int, nombre: str) -> MiembroHogar:
    nombre = (nombre or "").strip()
    if not nombre:
        raise DatoNoValido("el nombre no puede quedar vacío")
    miembro = _miembro(db, user_id)
    miembro.nombre = nombre[:40]
    db.commit()
    return miembro


def crear_invitacion(db: Session, user_id: int) -> str:
    miembro = asegurar_casa(db, user_id)
    if not miembro.titular:
        raise SoloTitular("solo quien creó la casa puede invitar")
    codigo = "".join(secrets.choice(_ALFABETO) for _ in range(8))
    db.add(InvitacionHogar(hogar_id=miembro.hogar_id, codigo=codigo))
    db.commit()
    return codigo


def _invitacion(db: Session, codigo: str) -> InvitacionHogar:
    codigo = (codigo or "").strip().upper().replace(" ", "").replace("-", "")
    inv = db.query(InvitacionHogar).filter(InvitacionHogar.codigo == codigo).first()
    if not inv or inv.usada_por is not None:
        raise InvitacionNoValida("ese código no vale o ya se usó")
    creado = inv.creado
    if creado is not None:
        if creado.tzinfo is None:
            creado = creado.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - creado > timedelta(days=DIAS_INVITACION):
            raise InvitacionNoValida("ese código ha caducado: pide otro")
    return inv


def ver_invitacion(db: Session, codigo: str) -> tuple[Hogar, list[MiembroHogar]]:
    """Para la pantalla de "Te han invitado a la casa de ...", sin entrar todavía."""
    inv = _invitacion(db, codigo)
    hogar = db.get(Hogar, inv.hogar_id)
    return hogar, miembros(db, hogar.id)


def unirse(db: Session, codigo: str, user_id: int, nombre: str) -> MiembroHogar:
    """Entra en la casa del código.

    Si esa persona ya tenía una casa ella sola (por ejemplo, anotó algo antes
    de que la invitaran), lo suyo se trae: nada de lo anotado se pierde. Si
    ya comparte casa con alguien, no se la saca de ahí sin más.
    """
    inv = _invitacion(db, codigo)
    actual = miembro_de(db, user_id)
    if actual and actual.hogar_id == inv.hogar_id:
        return actual
    if actual:
        if len(miembros(db, actual.hogar_id)) > 1:
            raise YaEnOtraCasa("ya compartes otra casa")
        viejo = actual.hogar_id
        db.query(GastoCasa).filter(GastoCasa.hogar_id == viejo).update({"hogar_id": inv.hogar_id})
        db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == viejo).update({"hogar_id": inv.hogar_id})
        db.query(InvitacionHogar).filter(InvitacionHogar.hogar_id == viejo).delete()
        db.delete(actual)
        db.flush()
        db.query(Hogar).filter(Hogar.id == viejo).delete()
    miembro = MiembroHogar(hogar_id=inv.hogar_id, user_id=user_id, nombre=(nombre or "").strip()[:40] or "Sin nombre", titular=False)
    db.add(miembro)
    inv.usada_por = user_id
    db.commit()
    db.refresh(miembro)
    return miembro


def unirse_por_web(db: Session, codigo: str, nombre: str) -> tuple[MiembroHogar, str]:
    """Para quien no usa Telegram: se le da un id propio y un token de la web.

    El id es negativo: los de Telegram son positivos, así que no pueden
    chocar nunca.
    """
    if not (nombre or "").strip():
        raise DatoNoValido("dinos tu nombre")
    _invitacion(db, codigo)  # que falle antes de inventar nada
    while True:
        user_id = -(secrets.randbelow(2**52) + 1)
        if not miembro_de(db, user_id):
            break
    miembro = unirse(db, codigo, user_id, nombre)
    return miembro, generar_token(db, user_id)


def quitar_miembro(db: Session, user_id: int, miembro_id: int) -> None:
    """El titular saca a alguien. Lo que anotó se queda: es de la casa."""
    yo = _miembro(db, user_id)
    if not yo.titular:
        raise SoloTitular("solo quien creó la casa puede quitar a alguien")
    otro = db.get(MiembroHogar, miembro_id)
    if not otro or otro.hogar_id != yo.hogar_id:
        raise NoEncontrado("no está en tu casa")
    if otro.id == yo.id:
        raise DatoNoValido("no puedes quitarte a ti")
    db.delete(otro)
    db.commit()


# --- Gastos -----------------------------------------------------------------


def _validar_gasto(concepto: str, importe: Decimal, fecha: date) -> str:
    concepto = (concepto or "").strip()
    if not concepto:
        raise DatoNoValido("falta en qué fue el gasto")
    if importe is None or importe <= 0:
        raise DatoNoValido("el importe tiene que ser mayor que cero")
    if importe >= 100000:
        raise DatoNoValido("ese importe parece un error")
    if fecha > hoy_local():
        raise DatoNoValido("la fecha no puede ser futura")
    return concepto


def crear_gasto(
    db: Session,
    user_id: int,
    concepto: str,
    importe: Decimal,
    fecha: date | None = None,
    categoria: str | None = None,
    origen: str = "web",
    pagado_por: int | None = None,
) -> GastoCasa:
    yo = asegurar_casa(db, user_id)
    fecha = fecha or hoy_local()
    concepto = _validar_gasto(concepto, Decimal(importe), fecha)
    quien = user_id
    if pagado_por is not None and pagado_por != user_id:
        otro = miembro_de(db, pagado_por)
        if not otro or otro.hogar_id != yo.hogar_id:
            raise DatoNoValido("esa persona no es de tu casa")
        quien = pagado_por
    gasto = GastoCasa(
        hogar_id=yo.hogar_id,
        user_id=quien,
        fecha=fecha,
        concepto=concepto[:200],
        importe=Decimal(importe),
        categoria=categoria if categoria in reglas.CATEGORIAS else reglas.categoria_de(concepto),
        origen=origen,
    )
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


def anotar_texto(db: Session, user_id: int, texto: str, origen: str = "bot") -> GastoCasa | None:
    """"-45 súper", "pagué 60 de luz": un gasto. Sin importe, None."""
    leido = reglas.interpretar_gasto(texto, hoy_local())
    if not leido:
        return None
    return crear_gasto(db, user_id, leido.concepto, leido.importe, leido.fecha, origen=origen)


def _gasto(db: Session, user_id: int, gasto_id: int) -> GastoCasa:
    yo = _miembro(db, user_id)
    gasto = db.get(GastoCasa, gasto_id)
    if not gasto or gasto.hogar_id != yo.hogar_id:
        raise NoEncontrado("ese gasto no está en tu casa")
    return gasto


def actualizar_gasto(db: Session, user_id: int, gasto_id: int, cambios: dict) -> GastoCasa:
    gasto = _gasto(db, user_id, gasto_id)
    concepto = cambios.get("concepto", gasto.concepto)
    importe = Decimal(cambios.get("importe", gasto.importe))
    fecha = cambios.get("fecha", gasto.fecha)
    gasto.concepto = _validar_gasto(concepto, importe, fecha)[:200]
    gasto.importe = importe
    gasto.fecha = fecha
    if "categoria" in cambios:
        if cambios["categoria"] not in reglas.CATEGORIAS:
            raise DatoNoValido("esa categoría no existe")
        gasto.categoria = cambios["categoria"]
    if cambios.get("pagado_por") is not None:
        otro = miembro_de(db, cambios["pagado_por"])
        if not otro or otro.hogar_id != gasto.hogar_id:
            raise DatoNoValido("esa persona no es de tu casa")
        gasto.user_id = otro.user_id
    db.commit()
    db.refresh(gasto)
    return gasto


def borrar_gasto(db: Session, user_id: int, gasto_id: int) -> None:
    db.delete(_gasto(db, user_id, gasto_id))
    db.commit()


def listar_gastos(db: Session, user_id: int, desde: date, hasta: date) -> list[GastoCasa]:
    yo = asegurar_casa(db, user_id)
    return (
        db.query(GastoCasa)
        .filter(GastoCasa.hogar_id == yo.hogar_id, GastoCasa.fecha >= desde, GastoCasa.fecha <= hasta)
        .order_by(GastoCasa.fecha.desc(), GastoCasa.id.desc())
        .all()
    )


@dataclass
class Parte:
    nombre: str
    total: Decimal


@dataclass
class ResumenCasa:
    total: Decimal
    por_categoria: list[Parte]
    por_persona: list[Parte]
    anterior: Decimal  # el mismo número de días justo antes, para comparar


def resumen(db: Session, user_id: int, desde: date, hasta: date) -> ResumenCasa:
    """Cuánto se ha gastado en la casa, en qué y quién.

    Las sumas las hace la base; `func.sum` sobre un importe ya da euros.
    """
    yo = asegurar_casa(db, user_id)
    base = db.query(GastoCasa).filter(GastoCasa.hogar_id == yo.hogar_id)

    def suma(d: date, h: date) -> Decimal:
        valor = base.filter(GastoCasa.fecha >= d, GastoCasa.fecha <= h).with_entities(func.sum(GastoCasa.importe)).scalar()
        return Decimal(valor or 0)

    en_rango = base.filter(GastoCasa.fecha >= desde, GastoCasa.fecha <= hasta)
    cats = (
        en_rango.with_entities(GastoCasa.categoria, func.sum(GastoCasa.importe))
        .group_by(GastoCasa.categoria)
        .all()
    )
    personas = dict(
        en_rango.with_entities(GastoCasa.user_id, func.sum(GastoCasa.importe)).group_by(GastoCasa.user_id).all()
    )
    nombres = {m.user_id: m.nombre for m in miembros(db, yo.hogar_id)}
    por_persona = [Parte(nombres[u], Decimal(personas.get(u) or 0)) for u in nombres]
    # Lo que pagó alguien que ya no está en la casa no desaparece del total.
    fuera = sum((Decimal(v or 0) for u, v in personas.items() if u not in nombres), Decimal(0))
    if fuera:
        por_persona.append(Parte("Otros", fuera))
    dias = (hasta - desde).days + 1
    return ResumenCasa(
        total=suma(desde, hasta),
        por_categoria=sorted((Parte(c, Decimal(t or 0)) for c, t in cats), key=lambda p: -p.total),
        por_persona=por_persona,
        anterior=suma(desde - timedelta(days=dias), desde - timedelta(days=1)),
    )


# --- Lista de la compra y despensa -----------------------------------------


def listar_articulos(db: Session, user_id: int) -> list[ArticuloCompra]:
    yo = asegurar_casa(db, user_id)
    return (
        db.query(ArticuloCompra)
        .filter(ArticuloCompra.hogar_id == yo.hogar_id)
        .order_by(ArticuloCompra.hay, ArticuloCompra.cambiado.desc(), ArticuloCompra.id.desc())
        .all()
    )


def anadir(db: Session, user_id: int, textos: list[str]) -> list[ArticuloCompra]:
    """Pone cosas en la lista. Lo que ya está en la lista no se repite; lo
    que estaba en la despensa vuelve a la lista (se habrá acabado)."""
    yo = asegurar_casa(db, user_id)
    existentes = {reglas.sin_tildes(a.texto): a for a in db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == yo.hogar_id)}
    resultado = []
    for texto in textos:
        texto = (texto or "").strip()[:120]
        if not texto:
            continue
        clave = reglas.sin_tildes(texto)
        articulo = existentes.get(clave)
        if articulo:
            if articulo.hay:
                articulo.hay = False
                articulo.cambiado = func.now()
            resultado.append(articulo)
            continue
        articulo = ArticuloCompra(hogar_id=yo.hogar_id, texto=texto[:1].upper() + texto[1:], anadido_por=user_id)
        db.add(articulo)
        existentes[clave] = articulo
        resultado.append(articulo)
    db.commit()
    for a in resultado:
        db.refresh(a)
    return resultado


def _articulo(db: Session, user_id: int, articulo_id: int) -> ArticuloCompra:
    yo = _miembro(db, user_id)
    articulo = db.get(ArticuloCompra, articulo_id)
    if not articulo or articulo.hogar_id != yo.hogar_id:
        raise NoEncontrado("eso no está en tu lista")
    return articulo


def marcar(db: Session, user_id: int, articulo_id: int, hay: bool) -> ArticuloCompra:
    """hay=True: comprado (pasa a la despensa). hay=False: se acabó (a la lista)."""
    articulo = _articulo(db, user_id, articulo_id)
    articulo.hay = hay
    articulo.cambiado = func.now()
    db.commit()
    db.refresh(articulo)
    return articulo


def renombrar_articulo(db: Session, user_id: int, articulo_id: int, texto: str) -> ArticuloCompra:
    texto = (texto or "").strip()
    if not texto:
        raise DatoNoValido("no puede quedar vacío")
    articulo = _articulo(db, user_id, articulo_id)
    articulo.texto = texto[:120]
    db.commit()
    return articulo


def borrar_articulo(db: Session, user_id: int, articulo_id: int) -> None:
    db.delete(_articulo(db, user_id, articulo_id))
    db.commit()


def vaciar_comprados(db: Session, user_id: int) -> int:
    """Quita de la despensa todo lo que había: para empezar de cero."""
    yo = _miembro(db, user_id)
    n = db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == yo.hogar_id, ArticuloCompra.hay.is_(True)).delete()
    db.commit()
    return n


def tachar_comprado(db: Session, user_id: int, lineas: list[str]) -> list[ArticuloCompra]:
    """Con las líneas de un ticket del súper, tacha de la lista lo comprado."""
    yo = miembro_de(db, user_id)
    if not yo or not lineas:
        return []
    faltan = db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == yo.hogar_id, ArticuloCompra.hay.is_(False)).all()
    tachados = [a for a in faltan if any(reglas.coincide(a.texto, l) for l in lineas)]
    for a in tachados:
        a.hay = True
        a.cambiado = func.now()
    db.commit()
    return tachados


# --- Qué hago de comer -----------------------------------------------------


async def sugerir_recetas(db: Session, user_id: int, preferencias: str = "") -> list[dict]:
    """Recetas con lo que hay en la despensa (y lo que se diga además).

    Puede lanzar `cocina.RecetasNoDisponibles` (sin clave) o
    `cocina.ErrorDeRecetas` (el servicio falló).
    """
    hay = [a.texto for a in listar_articulos(db, user_id) if a.hay]
    if not hay and not preferencias.strip():
        raise DatoNoValido("dime qué tienes en casa o marca lo que has comprado")
    return await cocina.pedir_recetas(hay, preferencias)


# --- Lo que llega escrito, dictado o en foto --------------------------------


@dataclass
class Anotado:
    """Lo que se hizo con un texto: un gasto, cosas para la lista, o nada."""

    gasto: GastoCasa | None = None
    articulos: list[ArticuloCompra] | None = None


def anotar_libre(db: Session, user_id: int, texto: str, origen: str = "bot") -> Anotado:
    """La regla de lo que se escribe a Casa, en un solo sitio (bot, voz y web).

    - "comprar ...", "... a la lista": a la lista, aunque lleve números
      ("comprar 6 huevos").
    - Con importe: un gasto ("-45 súper", "pagué 60 de luz").
    - Sin importe: cosas que faltan ("leche, huevos y pan"). Nada se pierde
      por no llevar precio, igual que en el negocio.
    """
    texto = (texto or "").strip()
    if not texto:
        raise DatoNoValido("no has escrito nada")
    if not reglas.es_para_la_lista(texto):
        gasto = anotar_texto(db, user_id, texto, origen)
        if gasto:
            return Anotado(gasto=gasto)
    articulos = reglas.articulos_de(texto)
    if not articulos:
        raise DatoNoValido("no he entendido qué apuntar")
    return Anotado(articulos=anadir(db, user_id, articulos))


@dataclass
class TicketDeCasa:
    gasto: GastoCasa | None
    tachados: list[ArticuloCompra]
    fecha_supuesta: bool


async def escanear_ticket(db: Session, user_id: int, imagen: bytes, mime: str, texto: str | None) -> TicketDeCasa:
    """Un ticket del súper: se anota como gasto de casa y tacha lo comprado.

    Lo lee el mismo modelo que los tickets del negocio y se filtra igual. La
    foto no se guarda: en casa no hay gestoría que pida el papel. Sin total
    leído no se anota nada (como en el negocio), pero lo comprado sí se tacha.
    Puede lanzar `LecturaNoDisponible`, `ErrorDeLectura` o `FacturaNoValida`.
    """
    from app.dominio.tickets import interpretar_lectura
    from app.nucleo.lectura_tickets import leer_ticket
    from app.servicios.facturas import imagen_para_leer

    asegurar_casa(db, user_id)
    para_leer, tipo = imagen_para_leer(imagen, mime)
    leido = interpretar_lectura(await leer_ticket(para_leer, tipo), hoy_local())
    lineas = [str(l.get("descripcion") or "") for l in (leido.detalle.get("lineas") or []) if isinstance(l, dict)]
    tachados = tachar_comprado(db, user_id, lineas)
    if leido.total is None:
        return TicketDeCasa(gasto=None, tachados=tachados, fecha_supuesta=False)
    concepto = (texto or "").strip() or leido.comercio or leido.concepto_sugerido
    gasto = crear_gasto(
        db,
        user_id,
        concepto,
        leido.total,
        leido.fecha or hoy_local(),
        categoria=reglas.categoria_de(f"{concepto} {leido.comercio or ''}"),
        origen="ticket",
    )
    return TicketDeCasa(gasto=gasto, tachados=tachados, fecha_supuesta=leido.fecha is None)
