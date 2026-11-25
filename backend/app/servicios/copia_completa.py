"""Sacar todo lo de una persona en una copia, y volver a meterlo.

La copia en CSV solo llevaba apuntes, y restaurarla los devolvía sueltos. Esta
lleva también clientes, trabajos, citas, hábitos, ajustes, los emisores que
la app ha aprendido y Casa, con los enlaces entre unas cosas y otras. El
formato del fichero es cosa de `dominio/copia_completa.py`.

Las reglas al restaurar son las de la copia en CSV, llevadas a todo:

- **Lo que hay en la base manda; de la copia solo entra lo que falta.** Cada
  cosa tiene su forma de saber si "ya está" (`_clave_*`), y se cuenta en vez
  de buscar uno a uno: dos gasolinas de 45 el mismo día son dos.
  Restaurar la misma copia dos veces no duplica nada.
- **Un hueco sí se rellena.** Si un apunte ya estaba pero suelto (porque se
  restauró antes desde el CSV), se vuelve a colgar de su trabajo y de su
  cliente. No pisa nada: un apunte que ya está en otro trabajo se queda donde
  está.
- **Siempre se enseña antes.** `planificar()` hace la restauración entera y
  la deshace: así lo que se enseña es exactamente lo que va a pasar, sin una
  segunda forma de contarlo que pueda decir otra cosa.

Lo que no puede volver: las fotos de los tickets (no van en la copia) y el
acceso a la web de quien entró en Casa solo por la web (los tokens no van).
Un cobro que tenía su factura emitida colgada queda marcado a mano para la
gestoría si va suelto, para que no desaparezca del parte al perder el papel.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from app.dominio.copia_completa import CopiaCompleta, empaquetar
from app.dominio.models import (
    Ajuste,
    Apunte,
    ArticuloCompra,
    Cita,
    Cliente,
    EmisorPropio,
    GastoCasa,
    Habito,
    HabitoHecho,
    Hogar,
    MiembroHogar,
    MovimientoCartera,
    Trabajo,
)
from app.nucleo.tiempo import hoy_local
from app.servicios.export import exportar_todo

_CENTIMO = Decimal("0.01")

# Lo que se cuenta al restaurar, en el orden en que se enseña.
SECCIONES = (
    ("apuntes", "apunte", "apuntes"),
    ("clientes", "cliente", "clientes"),
    ("trabajos", "trabajo", "trabajos"),
    ("citas", "cita", "citas"),
    ("habitos", "hábito", "hábitos"),
    ("dias_habito", "día de hábito cumplido", "días de hábito cumplidos"),
    ("ajustes", "ajuste (avisos y correo)", "ajustes"),
    ("emisores", "dato de tus facturas aprendido", "datos de tus facturas aprendidos"),
    ("personas_casa", "persona de Casa", "personas de Casa"),
    ("gastos_casa", "gasto de Casa", "gastos de Casa"),
    ("cartera", "movimiento de cartera", "movimientos de cartera"),
    ("compra", "cosa de la lista de la compra", "cosas de la lista de la compra"),
)


# --- Sacar ------------------------------------------------------------------


def _papel(apunte: Apunte) -> str | None:
    if apunte.factura is None:
        return None
    return "emitida" if apunte.factura.emitida else "ticket"


def datos_de(db: Session, user_id: int) -> dict:
    """Todo lo de esa persona, como diccionarios listos para el JSON."""
    clientes = db.query(Cliente).filter(Cliente.user_id == user_id).order_by(Cliente.id).all()
    trabajos = db.query(Trabajo).filter(Trabajo.user_id == user_id).order_by(Trabajo.id).all()
    apuntes = (
        db.query(Apunte).filter(Apunte.user_id == user_id).order_by(Apunte.fecha, Apunte.id).all()
    )
    citas = db.query(Cita).filter(Cita.user_id == user_id).order_by(Cita.fecha, Cita.id).all()
    habitos = db.query(Habito).filter(Habito.user_id == user_id).order_by(Habito.id).all()
    ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
    emisores = db.query(EmisorPropio).filter(EmisorPropio.user_id == user_id).all()

    return {
        "creada": hoy_local(),
        # Para avisar si alguien restaura la copia de otra cuenta (la de Casa
        # se la manda a los dos, y un reenvío por despiste es fácil).
        "user_id": user_id,
        "clientes": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "telefono": c.telefono,
                "direccion": c.direccion,
                "notas": c.notas,
            }
            for c in clientes
        ],
        "trabajos": [
            {
                "id": t.id,
                "titulo": t.titulo,
                "descripcion": t.descripcion,
                "cliente_id": t.cliente_id,
                "fecha_inicio": t.fecha_inicio,
                "fecha_fin": t.fecha_fin,
                "facturado": bool(t.facturado),
                "resena": bool(t.resena),
            }
            for t in trabajos
        ],
        "apuntes": [
            {
                "fecha": a.fecha,
                "tipo": a.tipo,
                "concepto": a.concepto,
                "importe": a.importe,
                "pendiente": bool(a.pendiente),
                "hecha": bool(a.hecha),
                "origen": a.origen,
                "cliente_id": a.cliente_id,
                "trabajo_id": a.trabajo_id,
                "para_gestoria": bool(a.para_gestoria),
                "factura": _papel(a),
            }
            for a in apuntes
        ],
        "citas": [
            {
                "fecha": c.fecha,
                "fecha_fin": c.fecha_fin,
                "hora": c.hora,
                "titulo": c.titulo,
                "direccion": c.direccion,
                "notas": c.notas,
                "hecha": bool(c.hecha),
                "cliente_id": c.cliente_id,
                "trabajo_id": c.trabajo_id,
                "avisada_el": c.avisada_el,
            }
            for c in citas
        ],
        "habitos": [
            {
                "nombre": h.nombre,
                "dias": h.dias,
                "inicio": h.inicio,
                "recordar_a": h.recordar_a,
                "hechos": sorted(hecho.fecha for hecho in h.hechos),
            }
            for h in habitos
        ],
        "ajustes": (
            {"avisos_activos": bool(ajuste.avisos_activos), "correo": ajuste.correo}
            if ajuste
            else None
        ),
        "emisores_propios": [
            {"nif": e.nif, "nombre": e.nombre, "iban": e.iban} for e in emisores
        ],
        "casa": _casa_de(db, user_id),
    }


def _casa_de(db: Session, user_id: int) -> dict | None:
    miembro = db.query(MiembroHogar).filter(MiembroHogar.user_id == user_id).first()
    if miembro is None:
        return None
    hogar_id = miembro.hogar_id
    hogar = db.get(Hogar, hogar_id)
    miembros = db.query(MiembroHogar).filter(MiembroHogar.hogar_id == hogar_id).order_by(MiembroHogar.id)
    gastos = db.query(GastoCasa).filter(GastoCasa.hogar_id == hogar_id).order_by(GastoCasa.id)
    cartera = (
        db.query(MovimientoCartera)
        .filter(MovimientoCartera.hogar_id == hogar_id)
        .order_by(MovimientoCartera.id)
    )
    compra = db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == hogar_id).order_by(ArticuloCompra.id)
    return {
        "nombre": hogar.nombre if hogar else "Casa",
        "miembros": [
            {"user_id": m.user_id, "nombre": m.nombre, "titular": bool(m.titular), "efectivo": bool(m.efectivo)}
            for m in miembros
        ],
        "gastos": [
            {
                "id": g.id,
                "user_id": g.user_id,
                "fecha": g.fecha,
                "concepto": g.concepto,
                "importe": g.importe,
                "categoria": g.categoria,
                "origen": g.origen,
                "efectivo": bool(g.efectivo),
            }
            for g in gastos
        ],
        "cartera": [
            {
                "user_id": m.user_id,
                "fecha": m.fecha,
                "tipo": m.tipo,
                "importe": m.importe,
                "gasto_id": m.gasto_id,
                "hasta_gasto_id": m.hasta_gasto_id,
            }
            for m in cartera
        ],
        "compra": [
            {"texto": a.texto, "hay": bool(a.hay), "anadido_por": a.anadido_por} for a in compra
        ],
    }


def tiene_datos(datos: dict) -> bool:
    casa = datos.get("casa") or {}
    return any(
        datos.get(seccion)
        for seccion in ("clientes", "trabajos", "apuntes", "citas", "habitos")
    ) or bool(casa.get("gastos") or casa.get("compra") or casa.get("cartera"))


def contar(datos: dict) -> dict[str, int]:
    """Cuánto hay de cada cosa, para decirlo al mandar la copia."""
    casa = datos.get("casa") or {}
    return {
        "apuntes": len(datos.get("apuntes", [])),
        "clientes": len(datos.get("clientes", [])),
        "trabajos": len(datos.get("trabajos", [])),
        "citas": len(datos.get("citas", [])),
        "habitos": len(datos.get("habitos", [])),
        "gastos_casa": len(casa.get("gastos", [])),
        "compra": len(casa.get("compra", [])),
    }


def generar(db: Session, user_id: int) -> tuple[bytes, dict[str, int]] | None:
    """El ZIP de la copia y lo que lleva. None si no hay nada que guardar."""
    datos = datos_de(db, user_id)
    if not tiene_datos(datos):
        return None
    return empaquetar(datos, exportar_todo(db, user_id)), contar(datos)


def usuarios_con_datos(db: Session) -> list[int]:
    """A quién mandar la copia del domingo: a todo el que tenga algo guardado.

    Antes se mandaba solo a quien recibía el aviso de esa noche (quien había
    anotado algo ese mismo domingo): una semana sin apuntar el domingo era una
    semana sin copia. Solo ids de Telegram (positivos): quien entró solo por
    la web no tiene chat al que mandarla, y la descarga desde la web.
    """
    ids: set[int] = set()
    for modelo in (Apunte, Cliente, Trabajo, Cita, Habito, MiembroHogar):
        ids.update(fila[0] for fila in db.query(modelo.user_id).distinct())
    return sorted(i for i in ids if i and i > 0)


# --- Volver a meter ---------------------------------------------------------


@dataclass
class PlanCompleto:
    nuevos: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    ya_estaban: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reenlazados: int = 0
    apuntes_nuevos: list[dict] = field(default_factory=list)

    @property
    def total_nuevos(self) -> int:
        return sum(self.nuevos.values())

    @property
    def total_ya_estaban(self) -> int:
        return sum(self.ya_estaban.values())

    @property
    def hay_algo(self) -> bool:
        return self.total_nuevos > 0 or self.reenlazados > 0


class _Cajones:
    """Lo que ya hay, agrupado por su clave, para ir emparejando y contando."""

    def __init__(self, existentes, clave):
        self._clave = clave
        self._cajones: dict = defaultdict(list)
        for objeto in existentes:
            self._cajones[clave(objeto)].append(objeto)

    def sacar(self, clave):
        cajon = self._cajones.get(clave)
        return cajon.pop(0) if cajon else None


def _normal(texto: str | None) -> str:
    return (texto or "").strip().lower()


def _clave_importe(importe) -> Decimal:
    return Decimal(importe).quantize(_CENTIMO)


def _aplicar(db: Session, user_id: int, copia: CopiaCompleta) -> PlanCompleto:
    """Mete lo que falta y cuenta. No confirma: eso lo decide quien llama."""
    plan = PlanCompleto()

    # Clientes: por nombre. Dos "Ana Ruiz" en la copia y una en la base: falta una.
    clientes = _Cajones(
        db.query(Cliente).filter(Cliente.user_id == user_id), lambda c: _normal(c.nombre)
    )
    id_cliente: dict[int, int] = {}
    for c in copia.clientes:
        existente = clientes.sacar(_normal(c["nombre"]))
        if existente is None:
            existente = Cliente(
                user_id=user_id,
                nombre=c["nombre"],
                telefono=c["telefono"],
                direccion=c["direccion"],
                notas=c["notas"],
            )
            db.add(existente)
            db.flush()
            plan.nuevos["clientes"] += 1
        else:
            plan.ya_estaban["clientes"] += 1
        if c["id"] is not None:
            id_cliente[c["id"]] = existente.id

    # Trabajos: por título y fecha de inicio.
    trabajos = _Cajones(
        db.query(Trabajo).filter(Trabajo.user_id == user_id),
        lambda t: (_normal(t.titulo), t.fecha_inicio),
    )
    id_trabajo: dict[int, int] = {}
    for t in copia.trabajos:
        existente = trabajos.sacar((_normal(t["titulo"]), t["fecha_inicio"]))
        if existente is None:
            existente = Trabajo(
                user_id=user_id,
                titulo=t["titulo"],
                descripcion=t["descripcion"],
                cliente_id=id_cliente.get(t["cliente_id"]),
                fecha_inicio=t["fecha_inicio"],
                fecha_fin=t["fecha_fin"],
                facturado=t["facturado"],
                resena=t["resena"],
            )
            db.add(existente)
            db.flush()
            plan.nuevos["trabajos"] += 1
        else:
            plan.ya_estaban["trabajos"] += 1
        if t["id"] is not None:
            id_trabajo[t["id"]] = existente.id

    # Apuntes: misma regla que la copia en CSV (fecha, tipo, concepto e
    # importe; `pendiente` no cuenta, o un cobro de después volvería a deuda).
    apuntes = _Cajones(
        db.query(Apunte).filter(Apunte.user_id == user_id),
        lambda a: (a.fecha, a.tipo, a.concepto.strip(), _clave_importe(a.importe)),
    )
    for a in copia.apuntes:
        cliente_id = id_cliente.get(a["cliente_id"])
        trabajo_id = id_trabajo.get(a["trabajo_id"])
        existente = apuntes.sacar((a["fecha"], a["tipo"], a["concepto"], _clave_importe(a["importe"])))
        if existente is not None:
            plan.ya_estaban["apuntes"] += 1
            reenlazado = False
            if existente.trabajo_id is None and trabajo_id is not None:
                existente.trabajo_id = trabajo_id
                # Dentro de un trabajo manda el trabajo, como al meterlo a mano.
                existente.para_gestoria = False
                reenlazado = True
            if existente.cliente_id is None and cliente_id is not None:
                existente.cliente_id = cliente_id
                reenlazado = True
            plan.reenlazados += reenlazado
            continue
        para_gestoria = a["para_gestoria"]
        if trabajo_id is None and a["factura"] == "emitida" and a["tipo"] == "trabajo":
            # La factura no vuelve; sin esto, el cobro dejaría de ir a la gestoría.
            para_gestoria = True
        if trabajo_id is not None:
            para_gestoria = False
        db.add(
            Apunte(
                user_id=user_id,
                fecha=a["fecha"],
                tipo=a["tipo"],
                concepto=a["concepto"],
                importe=a["importe"] if a["tipo"] != "nota" else Decimal("0"),
                pendiente=a["pendiente"] and a["tipo"] == "trabajo",
                hecha=a["hecha"] and a["tipo"] == "nota",
                origen=a["origen"],
                cliente_id=cliente_id,
                trabajo_id=trabajo_id,
                para_gestoria=para_gestoria and a["tipo"] != "nota",
            )
        )
        plan.nuevos["apuntes"] += 1
        plan.apuntes_nuevos.append(a)

    # Citas: por día, hora y título.
    citas = _Cajones(
        db.query(Cita).filter(Cita.user_id == user_id),
        lambda c: (c.fecha, c.hora, _normal(c.titulo)),
    )
    for c in copia.citas:
        if citas.sacar((c["fecha"], c["hora"], _normal(c["titulo"]))) is not None:
            plan.ya_estaban["citas"] += 1
            continue
        db.add(
            Cita(
                user_id=user_id,
                fecha=c["fecha"],
                fecha_fin=c["fecha_fin"],
                hora=c["hora"],
                titulo=c["titulo"],
                direccion=c["direccion"],
                notas=c["notas"],
                hecha=c["hecha"],
                cliente_id=id_cliente.get(c["cliente_id"]),
                trabajo_id=id_trabajo.get(c["trabajo_id"]),
                # Lo ya avisado no se vuelve a avisar.
                avisada_el=c["avisada_el"],
            )
        )
        plan.nuevos["citas"] += 1

    # Hábitos: por nombre; los días cumplidos se suman sin repetir.
    habitos = _Cajones(
        db.query(Habito).filter(Habito.user_id == user_id), lambda h: _normal(h.nombre)
    )
    for h in copia.habitos:
        existente = habitos.sacar(_normal(h["nombre"]))
        if existente is None:
            existente = Habito(
                user_id=user_id,
                nombre=h["nombre"],
                dias=h["dias"],
                inicio=h["inicio"],
                recordar_a=h["recordar_a"],
            )
            db.add(existente)
            db.flush()
            plan.nuevos["habitos"] += 1
            ya_hechos = set()
        else:
            plan.ya_estaban["habitos"] += 1
            ya_hechos = {hecho.fecha for hecho in existente.hechos}
        for dia in h["hechos"]:
            if dia in ya_hechos:
                plan.ya_estaban["dias_habito"] += 1
                continue
            db.add(HabitoHecho(habito_id=existente.id, fecha=dia))
            plan.nuevos["dias_habito"] += 1

    # Ajustes: solo si no había; un correo vacío se rellena.
    if copia.ajustes:
        ajuste = db.query(Ajuste).filter(Ajuste.user_id == user_id).first()
        if ajuste is None:
            db.add(
                Ajuste(
                    user_id=user_id,
                    avisos_activos=copia.ajustes["avisos_activos"],
                    correo=copia.ajustes["correo"],
                )
            )
            plan.nuevos["ajustes"] += 1
        elif not ajuste.correo and copia.ajustes["correo"]:
            ajuste.correo = copia.ajustes["correo"]
            plan.nuevos["ajustes"] += 1
        else:
            plan.ya_estaban["ajustes"] += 1

    # Emisores aprendidos: las tres cosas iguales es el mismo.
    emisores = _Cajones(
        db.query(EmisorPropio).filter(EmisorPropio.user_id == user_id),
        lambda e: (e.nif, _normal(e.nombre), e.iban),
    )
    for e in copia.emisores_propios:
        if emisores.sacar((e["nif"], _normal(e["nombre"]), e["iban"])) is not None:
            plan.ya_estaban["emisores"] += 1
            continue
        db.add(EmisorPropio(user_id=user_id, nif=e["nif"], nombre=e["nombre"], iban=e["iban"]))
        plan.nuevos["emisores"] += 1

    if copia.casa:
        _aplicar_casa(db, user_id, copia.casa, plan)

    db.flush()
    # Lo que se ha contado como nuevo pero está vacío no se enseña.
    plan.nuevos = {k: v for k, v in plan.nuevos.items() if v}
    plan.ya_estaban = {k: v for k, v in plan.ya_estaban.items() if v}
    return plan


def _aplicar_casa(db: Session, user_id: int, casa: dict, plan: PlanCompleto) -> None:
    """Casa vuelve a la casa de quien restaura; si no tiene, se crea.

    Las demás personas de la copia entran solo si no están ya en otra casa
    (una persona solo vive en una). Quien entró solo por la web vuelve como
    persona, para que sus gastos digan quién pagó, pero necesita una
    invitación nueva para entrar: su token no va en la copia.
    """
    miembro = db.query(MiembroHogar).filter(MiembroHogar.user_id == user_id).first()
    de_la_copia = {m["user_id"]: m for m in casa["miembros"]}
    if miembro is None:
        hogar = Hogar(nombre=casa["nombre"])
        db.add(hogar)
        db.flush()
        hogar_id = hogar.id
        hay_titular = any(m["titular"] for m in casa["miembros"])
    else:
        hogar_id = miembro.hogar_id
        hay_titular = True  # la casa ya tiene el suyo

    ya_en_alguna = {
        fila[0]
        for fila in db.query(MiembroHogar.user_id).filter(
            MiembroHogar.user_id.in_([user_id, *de_la_copia])
        )
    }
    orden = [user_id] + [uid for uid in de_la_copia if uid != user_id]
    for uid in orden:
        if uid in ya_en_alguna:
            if uid in de_la_copia:
                plan.ya_estaban["personas_casa"] += 1
            continue
        datos = de_la_copia.get(uid, {"nombre": "Yo", "titular": True, "efectivo": True})
        titular = datos["titular"] if miembro is None else False
        if miembro is None and uid == user_id and not hay_titular:
            titular = True
        db.add(
            MiembroHogar(
                hogar_id=hogar_id,
                user_id=uid,
                nombre=datos["nombre"][:40],
                titular=titular,
                efectivo=datos["efectivo"],
            )
        )
        ya_en_alguna.add(uid)
        plan.nuevos["personas_casa"] += 1
    db.flush()

    gastos = _Cajones(
        db.query(GastoCasa).filter(GastoCasa.hogar_id == hogar_id),
        lambda g: (g.user_id, g.fecha, g.concepto.strip(), _clave_importe(g.importe)),
    )
    id_gasto: dict[int, int] = {}
    for g in casa["gastos"]:
        existente = gastos.sacar((g["user_id"], g["fecha"], g["concepto"], _clave_importe(g["importe"])))
        if existente is None:
            existente = GastoCasa(
                hogar_id=hogar_id,
                user_id=g["user_id"] if g["user_id"] is not None else user_id,
                fecha=g["fecha"],
                concepto=g["concepto"],
                importe=g["importe"],
                categoria=g["categoria"],
                origen=g["origen"],
                efectivo=g["efectivo"],
            )
            db.add(existente)
            db.flush()
            plan.nuevos["gastos_casa"] += 1
        else:
            plan.ya_estaban["gastos_casa"] += 1
        if g["id"] is not None:
            id_gasto[g["id"]] = existente.id

    cartera = _Cajones(
        db.query(MovimientoCartera).filter(MovimientoCartera.hogar_id == hogar_id),
        lambda m: (m.user_id, m.fecha, m.tipo, _clave_importe(m.importe)),
    )
    for m in casa["cartera"]:
        if m["user_id"] is None:
            continue
        if cartera.sacar((m["user_id"], m["fecha"], m["tipo"], _clave_importe(m["importe"]))) is not None:
            plan.ya_estaban["cartera"] += 1
            continue
        db.add(
            MovimientoCartera(
                hogar_id=hogar_id,
                user_id=m["user_id"],
                fecha=m["fecha"],
                tipo=m["tipo"],
                importe=m["importe"],
                gasto_id=id_gasto.get(m["gasto_id"]),
                hasta_gasto_id=id_gasto.get(m["hasta_gasto_id"]),
            )
        )
        plan.nuevos["cartera"] += 1

    en_la_lista = {
        _normal(a.texto)
        for a in db.query(ArticuloCompra).filter(ArticuloCompra.hogar_id == hogar_id)
    }
    for a in casa["compra"]:
        if _normal(a["texto"]) in en_la_lista:
            plan.ya_estaban["compra"] += 1
            continue
        db.add(ArticuloCompra(hogar_id=hogar_id, texto=a["texto"], hay=a["hay"], anadido_por=a["anadido_por"]))
        en_la_lista.add(_normal(a["texto"]))
        plan.nuevos["compra"] += 1


def planificar(db: Session, user_id: int, copia: CopiaCompleta) -> PlanCompleto:
    """Qué entraría si se restaura ahora. No deja nada escrito.

    Hace la restauración de verdad y la deshace: lo que se enseña es lo que
    pasará, contado por el mismo código. Ojo: deshace también cualquier cosa
    sin confirmar que hubiera en la sesión; se llama con una sesión limpia.
    """
    try:
        return _aplicar(db, user_id, copia)
    finally:
        db.rollback()


def restaurar(db: Session, user_id: int, copia: CopiaCompleta) -> PlanCompleto:
    """Mete lo que falta y lo confirma. Se vuelve a calcular aquí: entre la
    vista previa y el sí se puede haber anotado algo, y no puede duplicarse."""
    try:
        plan = _aplicar(db, user_id, copia)
    except Exception:
        db.rollback()
        raise
    db.commit()
    return plan
