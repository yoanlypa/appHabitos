"""Cómo se ve un apunte o un resumen en un mensaje de Telegram.

Solo presentación: aquí no se decide nada, solo se pinta lo que ya
calcularon los servicios. Los importes se escriben a la española
(1.234,50 €), que es como los va a leer quien usa el bot.
"""
from datetime import timedelta
from decimal import Decimal

from app.dominio.tickets import texto_de_vale

from app.dominio.models import Apunte
from app.nucleo.tiempo import hoy_local
from app.servicios.resumen import ResumenPeriodo


def euros(importe: Decimal) -> str:
    # Se formatea al estilo inglés y se intercambian los separadores, que es
    # más corto y fiable que depender del locale del sistema.
    entero_y_decimales = f"{importe:,.2f}"
    return entero_y_decimales.replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def apunte_creado(apunte: Apunte) -> str:
    if apunte.tipo == "nota":
        return f"Nota guardada: {apunte.concepto}  (#{apunte.id})"
    if apunte.tipo == "gasto":
        linea = f"Gasto anotado: {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"
    else:
        estado = "pendiente de cobro" if apunte.pendiente else "cobrado"
        linea = (
            f"Trabajo anotado ({estado}): {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"
        )
    # El día solo se dice cuando no es hoy: es cuando puede estar mal, y con
    # el nombre del día de la semana un día equivocado salta a la vista.
    if apunte.fecha != hoy_local():
        linea += f"\n📅 {dia_con_nombre(apunte.fecha).capitalize()}"
    return linea


def pregunta_si_es_gasto(palabra: str) -> str:
    """Bajo un trabajo cobrado cuyo concepto suena a gasto ("gasolina 45")."""
    return (
        f"⚠️ Lo he apuntado como dinero que ENTRA, pero «{palabra}» suena a gasto.\n"
        "Si lo es, toca «Es un gasto». La próxima vez: -45 gasolina"
    )


def escuchado(texto: str) -> str:
    """Lo que se entendió del audio, siempre delante de lo anotado.

    Sin esto, un "20" oído como "120" no se descubre hasta cuadrar el mes.
    """
    return f'He oído: «{texto}»'


def apunte_cobrado(apunte: Apunte) -> str:
    return f"Marcado como cobrado: {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"


def resumen(titulo: str, r: ResumenPeriodo) -> str:
    lineas = [
        titulo,
        f"Cobrado:   {euros(r.cobrado)}",
        f"Pendiente: {euros(r.pendiente)}",
        f"Gastos:    {euros(r.gastos)}",
        f"Neto:      {euros(r.neto)}",
    ]
    return "\n".join(lineas)


def ayuda() -> str:
    return (
        "Escríbeme lo que has hecho y lo anoto:\n"
        "  Cambio de grifo Ana 120     → trabajo cobrado\n"
        "  pendiente Reforma baño 980  → trabajo sin cobrar\n"
        "  -45 gasolina                → gasto\n"
        "  ayer -45 gasolina           → gasto de ayer\n"
        "  3/11 parking 2,75           → con su día delante\n"
        "  Llamar al fontanero martes  → nota, sin dinero\n\n"
        "Debajo de cada apunte tienes botones para cobrarlo, cambiarle el día, "
        "pasarlo de cobro a gasto o borrarlo: no hace falta recordar su número.\n\n"
        "También puedes mandarme:\n"
        "  🎤 una nota de voz: la escucho y la anoto igual\n"
        "  🧾 la foto o el PDF de un ticket o una factura: lo anoto y te devuelvo el PDF\n"
        "  📋 varios de golpe: un apunte por línea en un mensaje, un Excel o CSV "
        "(columnas fecha, concepto, importe), o una captura con varios pagos "
        "(escribe «lista» en la foto). Te enseño lo que he leído antes de guardar nada.\n\n"
        "Comandos:\n"
        "  /hoy — resumen y apuntes del día\n"
        "  /mes — resumen del mes\n"
        "  /trimestre — lo que llevas este trimestre\n"
        "  /deben — quién te debe dinero (y cobrarlo con un toque)\n"
        "  /agenda — lo que toca hoy\n"
        "  /manana — lo que toca mañana\n"
        "  /cita mañana 10:00 Cambiar grifo — apunta una cita\n"
        "      también vale: /cita 20 de septiembre a las 10am Ver la casa\n"
        "  /notas — el buzón de lo que no tiene fecha\n"
        "  /habitos — marca los hábitos de hoy\n"
        "  /facturas — los tickets del mes en un PDF ('/facturas pasado': el anterior)\n"
        "  /cliente Ana Ruiz 600111222 — da de alta un cliente\n"
        "  /web — entrar en la web\n"
        "  /copia — te mando todo en un CSV, por si acaso\n"
        "  /avisos on|off — resumen automático cada noche\n"
        "  /menu — vuelve a sacar los botones de abajo\n\n"
        "Con el número del apunte, por si lo prefieres a los botones:\n"
        "  /cobrado 12 · /borrar 12 · /fecha 12 15/10 · /hecha 12\n"
        "  /emitida 12 — una factura tuya que entró como gasto pasa a trabajo\n"
        "  /releer — pone en su día los tickets que quedaron en el día equivocado\n"
        "  /reparar — corrige el cliente de tus facturas leídas al revés\n\n"
        "Si algún día pierdes datos, reenvíame una de las copias y vuelvo a "
        "meter lo que falte."
    )


def cuando(cita) -> str:
    """El día, o el rango si dura varios. "9/09 a 11/09" se lee de un vistazo."""
    inicio = cita.fecha.strftime("%d/%m")
    if cita.fecha_fin is None:
        return inicio
    return f"{inicio} a {cita.fecha_fin.strftime('%d/%m')}"


_NOMBRE_DIA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def dia_con_nombre(fecha) -> str:
    """"el domingo 20/09", o "hoy" y "mañana" cuando toca.

    El día de la semana no es adorno: al confirmar una cita es lo que hace
    que un día equivocado salte a la vista. Un "20/09" suelto se lee sin
    mirarlo; un "sábado" cuando pensabas en el domingo, no.
    """
    hoy = hoy_local()
    if fecha == hoy:
        return "hoy"
    if fecha == hoy + timedelta(days=1):
        return "mañana"
    if fecha == hoy - timedelta(days=1):
        return "ayer"
    return f"el {_NOMBRE_DIA[fecha.weekday()]} {fecha.strftime('%d/%m')}"


def cita_creada(cita) -> str:
    hora = cita.hora.strftime(" a las %H:%M") if cita.hora else ""
    quien = f" — {cita.cliente.nombre}" if cita.cliente else ""
    if cita.fecha_fin:
        cuando_dura = f"desde {dia_con_nombre(cita.fecha)} hasta {dia_con_nombre(cita.fecha_fin)}"
    else:
        cuando_dura = f"para {dia_con_nombre(cita.fecha)}"
    return f"Apuntado {cuando_dura}{hora}: {cita.titulo}{quien}"


def lista_notas(notas: list) -> str:
    """El buzón: lo apuntado que aún no tiene ni fecha ni precio."""
    if not notas:
        return "No tienes notas pendientes."
    lineas = [f"Tienes {len(notas)} nota{'s' if len(notas) > 1 else ''}:"]
    for n in notas:
        quien = f" — {n.cliente.nombre}" if n.cliente else ""
        lineas.append(f"  #{n.id} {n.concepto}{quien} ({n.fecha.strftime('%d/%m')})")
    lineas.append("")
    lineas.append("Toca una cuando la cumplas (o /hecha <número>). Ponerles fecha, desde la web.")
    return "\n".join(lineas)


def nota_hecha(nota, hecha: bool = True) -> str:
    if hecha:
        return f"Hecha: {nota.concepto}"
    return f"De vuelta al buzón: {nota.concepto}  (#{nota.id})"


def alarma_almacenamiento(aviso: str) -> str:
    """Lo más grave que puede decir el bot: que lo que se apunta se va a perder."""
    return (
        "⚠️ OJO: LOS DATOS NO SE ESTÁN GUARDANDO.\n\n"
        f"{aviso}\n\n"
        "Lo que apuntes ahora se borrará en el próximo despliegue. "
        "Arréglalo en Railway antes de seguir apuntando."
    )


def _fila_de_copia(fila) -> str:
    cuando = fila.fecha.strftime("%d/%m/%Y")
    if fila.tipo == "nota":
        return f"{cuando}  nota: {fila.concepto}"
    signo = "−" if fila.tipo == "gasto" else ""
    sin_cobrar = " (pendiente)" if fila.pendiente and fila.tipo == "trabajo" else ""
    return f"{cuando}  {fila.concepto} — {signo}{euros(fila.importe)}{sin_cobrar}"


def plan_de_restauracion(plan, muestra: int = 8) -> str:
    """Lo que entraría al restaurar, antes de pedir el sí."""
    lineas = [f"En esta copia hay {plan.total} apuntes."]
    if plan.ya_estaban:
        lineas.append(f"{plan.ya_estaban} ya los tienes: esos no los toco.")
    lineas.append("")
    lineas.append(f"Faltan {len(plan.nuevas)}:")
    for fila in plan.nuevas[:muestra]:
        lineas.append(f"  {_fila_de_copia(fila)}")
    if len(plan.nuevas) > muestra:
        lineas.append(f"  … y {len(plan.nuevas) - muestra} más")
    lineas.append("")
    lineas.append(
        "Ojo: si borraste alguno a propósito después de hacer esta copia, volverá a entrar. "
        "Los clientes y las citas no van en la copia."
    )
    return "\n".join(lineas)


def copia_ya_estaba(plan) -> str:
    return f"Esta copia tiene {plan.total} apuntes y ya los tienes todos. No hay nada que restaurar."


def copia_no_valida(motivo) -> str:
    return (
        f"No puedo leer ese fichero: {motivo}.\n\n"
        "Vale una de las copias que te mando yo (el CSV de /copia), o un CSV o "
        "Excel con tres columnas en la primera fila: fecha, concepto, importe "
        "(y, si quieres, tipo: gasto o trabajo)."
    )


def copia_restaurada(cuantos: int) -> str:
    if cuantos == 0:
        return "No faltaba nada: ya estaba todo."
    plural = "s" if cuantos != 1 else ""
    return f"Restaurado{plural} {cuantos} apunte{plural}. Míralo en la web o con /mes."


def racha_texto(racha: int) -> str:
    if racha == 0:
        return "sin racha"
    if racha == 1:
        return "1 día seguido"
    return f"{racha} días seguidos"


def lista_habitos(resumenes) -> str:
    """Los hábitos de hoy. Los botones hacen el trabajo; el texto, la cuenta."""
    if not resumenes:
        return "Todavía no tienes hábitos. Créalos en la web, en la pestaña Hábitos."

    de_hoy = [r for r in resumenes if r.toca_hoy]
    lineas = ["Hábitos de hoy:" if de_hoy else "Hoy no te toca ningún hábito."]
    for resumen in de_hoy:
        marca = "✅" if resumen.hecho_hoy else "⬜"
        lineas.append(f"{marca} {resumen.habito.nombre} — {racha_texto(resumen.racha)}")

    otros = [r.habito.nombre for r in resumenes if not r.toca_hoy]
    if otros:
        lineas += ["", f"Hoy no tocan: {', '.join(otros)}"]
    if de_hoy:
        lineas += ["", "Toca uno para marcarlo o desmarcarlo."]
    return "\n".join(lineas)


def boton_habito(resumen) -> str:
    return f"{'✅' if resumen.hecho_hoy else '⬜'} {resumen.habito.nombre}"


def recordatorio_habito(resumen) -> str:
    texto = f"⏰ {resumen.habito.nombre}: hoy todavía no está."
    if resumen.racha:
        texto += f" Llevas {racha_texto(resumen.racha)}, no la pierdas."
    return texto


def habito_marcado(resumen) -> str:
    return f"✅ {resumen.habito.nombre}. Llevas {racha_texto(resumen.racha)}."


def recordatorio_de_notas(cuantas: int) -> str:
    """Una línea en el aviso de la noche, para que el buzón no sea un cajón."""
    if cuantas == 1:
        return "Tienes 1 nota sin fecha. Míralas con /notas."
    return f"Tienes {cuantas} notas sin fecha. Míralas con /notas."


def lista_citas(titulo: str, citas: list) -> str:
    if not citas:
        return f"{titulo}\nNada apuntado."
    lineas = [titulo]
    for c in citas:
        hora = c.hora.strftime("%H:%M") if c.hora else "  ·  "
        marca = "✓ " if c.hecha else ""
        donde = f" ({c.direccion})" if c.direccion else ""
        quien = f" — {c.cliente.nombre}" if c.cliente else ""
        dura = f" [hasta el {c.fecha_fin.strftime('%d/%m')}]" if c.fecha_fin else ""
        lineas.append(f"{hora}  {marca}{c.titulo}{quien}{donde}{dura}")
    return "\n".join(lineas)


def lista_deudas(pendientes: list) -> str:
    """Lo que te deben, con el nombre del cliente si el apunte lo tiene."""
    if not pendientes:
        return "No te debe nadie."
    total = sum(a.importe for a in pendientes)
    lineas = [f"Te deben {euros(total)}:"]
    for a in pendientes:
        quien = f" — {a.cliente.nombre}" if a.cliente else ""
        lineas.append(f"  #{a.id} {a.concepto}{quien}: {euros(a.importe)} ({a.fecha.strftime('%d/%m')})")
    lineas += ["", "Toca uno cuando te lo paguen."]
    return "\n".join(lineas)


def apunte_creado_con_cliente(apunte, cliente) -> str:
    """Igual que apunte_creado pero diciendo de quién ha quedado colgado.

    Se dice siempre: si el bot asigna cliente en silencio y se equivoca, hay
    que poder verlo en el momento y no tres semanas después al cobrar.
    """
    return f"{apunte_creado(apunte)}\n   → {cliente.nombre}"


def preguntar_cliente(nombre_repetido: str) -> str:
    return f"¿Qué {nombre_repetido}?"


def descripcion_corta(cliente) -> str:
    """Lo justo para distinguir a dos personas con el mismo nombre."""
    detalle = cliente.telefono or cliente.direccion
    return f"{cliente.nombre} · {detalle}" if detalle else cliente.nombre


def apunte_borrado(apunte) -> str:
    if apunte.tipo == "nota":
        return f"Borrada la nota: {apunte.concepto}"
    return f"Borrado: {apunte.concepto} — {euros(apunte.importe)}"


def resumen_trimestre(r) -> str:
    """El trimestre, con la estimación del 130 marcada como lo que es."""
    return "\n".join(
        [
            f"Trimestre {r.trimestre} de {r.anio}"
            f" ({r.desde.strftime('%d/%m')} a {r.hasta.strftime('%d/%m')}):",
            f"Cobrado:   {euros(r.cobrado)}",
            f"Gastos:    {euros(r.gastos)}",
            f"Neto:      {euros(r.neto)}",
            "",
            f"Pendiente de cobro: {euros(r.pendiente)}",
            "",
            f"Modelo 130 aproximado: {euros(r.estimacion_130)}",
            "Es una estimación al 20% del neto, para hacerte una idea.",
            "Confírmalo con tu gestor antes de pagar nada.",
        ]
    )


def ticket_anotado(apunte, datos, fecha_supuesta: bool = False) -> str:
    """Lo que se entendió del ticket, para verlo al momento y corregir si hace falta."""
    lineas = [
        f"🧾 Gasto anotado (#{apunte.id}): {apunte.concepto}",
        f"−{euros(apunte.importe)} · {dia_con_nombre(apunte.fecha)}",
    ]
    if fecha_supuesta:
        lineas.append(
            f"⚠️ No he podido leer la fecha del ticket y lo he puesto hoy. "
            f"Si es de otro día: /fecha {apunte.id} 15/10"
        )
    if datos.iva is not None:
        lineas.append(f"IVA: {euros(datos.iva)}")
    # Se dice en los dos sentidos: lo que no se marca no va, y eso hay que
    # saberlo al subirlo y no al cerrar el trimestre.
    if apunte.gestoria:
        lineas.append("📁 Va a la gestoría.")
    else:
        lineas.append(
            "No va a la gestoría. Si es de un trabajo o tiene que ir, márcalo en la web "
            "(Finanzas → Gestoría), o manda la foto con «para la gestoría»."
        )
    vales = datos.detalle.get("vales") or []
    if vales:
        lineas.append("")
        lineas.append("📌 Apuntado en tus notas para que no se te olvide:")
        lineas.extend(f"  {texto_de_vale(v, None)}" for v in vales)
        lineas.append("Márcalo con /hecha cuando lo uses.")
        lineas.append("")
    lineas.append(f"Si está mal: /borrar {apunte.id} y vuelve a mandarla.")
    lineas.append(f"Si es una factura TUYA a un cliente: /emitida {apunte.id}")
    return "\n".join(lineas)


def ticket_sin_total() -> str:
    return (
        "No he sabido leer el total de esa foto, así que no he anotado nada.\n"
        "Prueba con más luz y el ticket entero en la foto, o escríbemelo: "
        "-23,40 ferretería"
    )


def _mes(fecha) -> str:
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{meses[fecha.month - 1]} de {fecha.year}"


def facturas_del_mes(desde) -> str:
    return f"🧾 Tickets escaneados de {_mes(desde)}, uno por página."


def sin_facturas(desde) -> str:
    return (
        f"No hay tickets escaneados en {_mes(desde)}.\n"
        "Mándame la foto de un ticket y lo anoto como gasto."
    )


def fecha_cambiada(apunte) -> str:
    dia = dia_con_nombre(apunte.fecha)
    # "al martes 03/11", pero "a hoy" y "a ayer": salía "Movido al el martes".
    donde = f"al {dia[3:]}" if dia.startswith("el ") else f"a {dia}"
    return f"📅 Movido {donde} (#{apunte.id}): {apunte.concepto}"


def relectura(resultado) -> str:
    if not resultado.corregidas and not resultado.sin_fecha:
        return "Todos tus tickets ya tienen su fecha. No había nada que corregir."
    lineas = []
    if resultado.corregidas:
        lineas.append(f"📅 He puesto en su día {len(resultado.corregidas)} tickets:")
        for c in resultado.corregidas[:30]:
            lineas.append(
                f"  #{c.apunte.id} {c.apunte.concepto}: {c.antes:%d/%m} → {c.apunte.fecha:%d/%m/%Y}"
            )
    if resultado.sin_fecha:
        lineas.append(
            f"⚠️ En {resultado.sin_fecha} no he encontrado la fecha ni releyéndolos. "
            "Cámbiala a mano: /fecha <número> 15/10"
        )
    if resultado.quedan:
        lineas.append(f"Quedan {resultado.quedan} por revisar: manda /releer otra vez.")
    return "\n".join(lineas)


def emitidas_del_mes(desde) -> str:
    return f"📤 Tus facturas emitidas de {_mes(desde)}, una por página."


def boton_trabajo(apunte) -> str:
    return f"{apunte.fecha:%d/%m} · {apunte.concepto[:30]} · {euros(apunte.importe)}"


def preguntar_trabajo(emitida) -> str:
    quien = f" de {emitida.cliente.nombre}" if emitida.cliente else ""
    return (
        f"📤 Es una factura tuya{quien}. Tengo varios trabajos pendientes que "
        "podrían ser el suyo. ¿De cuál es?"
    )


def factura_emitida(emitida, fecha_supuesta: bool = False) -> str:
    """Lo que se hizo con una factura de Yoa: a qué trabajo va y si está cobrada."""
    a = emitida.apunte
    lineas = [f"📤 Factura tuya anotada como trabajo (#{a.id}): {a.concepto}"]
    lineas.append(f"+{euros(a.importe)} · {dia_con_nombre(a.fecha)}")
    if emitida.vinculada:
        lineas.append("La he colgado del trabajo que ya tenías apuntado (no se cuenta dos veces).")
    if emitida.cliente is not None:
        alta = " (nuevo, dado de alta con los datos de la factura)" if emitida.cliente_nuevo else ""
        lineas.append(f"Cliente: {emitida.cliente.nombre}{alta}")
    if a.pendiente:
        lineas.append(f"⏳ Pendiente de cobro. Cuando te paguen: /cobrado {a.id}")
    else:
        lineas.append("✅ Cobrada.")
    if fecha_supuesta:
        lineas.append(f"⚠️ No he leído la fecha de la factura: la he puesto hoy. Cámbiala con /fecha {a.id} 15/10")
    return "\n".join(lineas)


def factura_vinculada(apunte, nuevo: bool) -> str:
    estado = "⏳ Pendiente de cobro" if apunte.pendiente else "✅ Cobrada"
    como = "como trabajo nuevo" if nuevo else "en el trabajo"
    return (
        f"📤 Factura anotada {como} (#{apunte.id}): {apunte.concepto}\n"
        f"+{euros(apunte.importe)} · {estado}"
    )


def emitidas_reparadas(apuntes) -> str:
    if not apuntes:
        return "Tus facturas ya estaban bien: no he cambiado nada."
    lineas = [f"🔧 He corregido {len(apuntes)} factura(s):"]
    for a in apuntes:
        quien = a.cliente.nombre if a.cliente else "sin cliente"
        lineas.append(f"  #{a.id} {a.concepto} → cliente: {quien}")
    return "\n".join(lineas)


# --- Lo que se ve al tocar los botones de un apunte ---------------------------


def tipo_cambiado(apunte) -> str:
    if apunte.tipo == "gasto":
        return f"Cambiado a GASTO: {apunte.concepto} — −{euros(apunte.importe)}  (#{apunte.id})"
    return f"Cambiado a COBRO: {apunte.concepto} — +{euros(apunte.importe)}  (#{apunte.id})"


def confirmar_borrado(apunte) -> str:
    aviso = "\nSe irá también la foto de su ticket." if apunte.factura is not None else ""
    if apunte.tipo == "nota":
        return f"¿Borro esta nota?\n{apunte.concepto}  (#{apunte.id})"
    return f"¿Borro esto?\n{apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id}){aviso}"


def pedir_fecha(apunte) -> str:
    return (
        f"¿De qué día es «{apunte.concepto}»?\n"
        "Escríbeme solo el día: 15/10, 3 de octubre, ayer…"
    )


def lista_del_dia(apuntes: list, muestra: int = 12) -> str:
    """Los apuntes de hoy debajo del resumen: las cifras dicen cuánto, esto dice qué."""
    if not apuntes:
        return "Hoy todavía no has apuntado nada."
    lineas = []
    for a in apuntes[:muestra]:
        if a.tipo == "gasto":
            cuanto = f"−{euros(a.importe)}"
        else:
            cuanto = f"+{euros(a.importe)}" + (" ⏳" if a.pendiente else "")
        lineas.append(f"  #{a.id} {a.concepto}: {cuanto}")
    if len(apuntes) > muestra:
        lineas.append(f"  … y {len(apuntes) - muestra} más (en la web)")
    return "\n".join(lineas)


def boton_cobrar(apunte) -> str:
    quien = f"{apunte.cliente.nombre.split()[0]} · " if apunte.cliente else ""
    return f"✅ {quien}{apunte.concepto[:24]} · {euros(apunte.importe)}"


def boton_nota(nota) -> str:
    return f"✓ {nota.concepto[:40]}"


# --- Importar varios de golpe -------------------------------------------------


def _fila_de_movimiento(m) -> str:
    cuando = m.fecha.strftime("%d/%m")
    if m.tipo is None:
        return f"{cuando}  {m.concepto} — {euros(m.importe)}"
    signo = "−" if m.tipo == "gasto" else "+"
    sin_cobrar = " (pendiente)" if m.pendiente else ""
    return f"{cuando}  {m.concepto} — {signo}{euros(m.importe)}{sin_cobrar}"


def plan_de_importacion(plan, muestra: int = 20) -> str:
    """Lo leído, antes de guardar nada: es el momento de ver un importe mal leído."""
    lineas = []
    if plan.nuevos:
        total = sum(m.importe for m in plan.nuevos)
        plural = "s" if len(plan.nuevos) != 1 else ""
        lineas.append(f"📋 He leído {len(plan.nuevos)} movimiento{plural} nuevo{plural} ({euros(total)}):")
        for m in plan.nuevos[:muestra]:
            lineas.append(f"  {_fila_de_movimiento(m)}")
        if len(plan.nuevos) > muestra:
            lineas.append(f"  … y {len(plan.nuevos) - muestra} más")
    if plan.repetidos:
        if lineas:
            lineas.append("")
        cuantos = len(plan.repetidos)
        lineas.append(
            f"Est{'os' if cuantos != 1 else 'e'} {cuantos} ya l{'os' if cuantos != 1 else 'o'} "
            "tienes (mismo día e importe), no los toco:"
            if plan.nuevos
            else f"He leído {cuantos} y ya los tienes todos (mismo día e importe):"
        )
        for m in plan.repetidos[:8]:
            lineas.append(f"  {_fila_de_movimiento(m)}")
        if cuantos > 8:
            lineas.append(f"  … y {cuantos - 8} más")
    if plan.nuevos:
        lineas += ["", "Repásalos: todavía no he guardado nada."]
    return "\n".join(lineas)


def preguntar_tipo_de_importacion(movimientos, muestra: int = 12) -> str:
    total = sum(m.importe for m in movimientos)
    lineas = [f"📋 He leído {len(movimientos)} movimientos ({euros(total)}):"]
    for m in movimientos[:muestra]:
        lineas.append(f"  {_fila_de_movimiento(m)}")
    if len(movimientos) > muestra:
        lineas.append(f"  … y {len(movimientos) - muestra} más")
    lineas += ["", "El fichero no dice si son gastos o cobros. ¿Qué son?"]
    return "\n".join(lineas)


def importacion_hecha(apuntes: list, ya_estaban: int = 0) -> str:
    if not apuntes:
        return "No faltaba ninguno: ya los tenías todos. No he añadido nada."
    plural = "s" if len(apuntes) != 1 else ""
    gastos = sum(a.importe for a in apuntes if a.tipo == "gasto")
    entra = sum(a.importe for a in apuntes if a.tipo == "trabajo")
    lineas = [f"✅ Añadido{plural} {len(apuntes)} movimiento{plural}."]
    if gastos:
        lineas.append(f"Gastos: −{euros(gastos)}")
    if entra:
        lineas.append(f"Trabajos: +{euros(entra)}")
    if ya_estaban:
        lineas.append(f"{ya_estaban} ya estaban y no los he repetido.")
    lineas.append("Míralos con /mes o en la web (Finanzas).")
    return "\n".join(lineas)


def importacion_deshecha(cuantos: int) -> str:
    if cuantos == 0:
        return "Ya no quedaba nada de esa importación."
    return f"Deshecho: he quitado los {cuantos} movimientos que acababa de añadir."


def importacion_caducada() -> str:
    return (
        "Ya no tengo esa lista a mano (puede que me haya reiniciado). "
        "Mándamela otra vez y la vuelvo a leer."
    )


def captura_sin_movimientos() -> str:
    return (
        "No he sabido leer varios movimientos en esa imagen, así que no he anotado nada.\n"
        "Prueba con la captura entera y nítida, o escríbemelos uno por línea:\n"
        "3/11 -2,75 parking\n4/11 -2,75 parking"
    )


def importacion_caducada_para_deshacer() -> str:
    return "Eso ya no lo puedo deshacer de golpe. Bórralos uno a uno: /borrar <número>."
