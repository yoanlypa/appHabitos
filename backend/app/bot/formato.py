"""Cómo se ve un apunte o un resumen en un mensaje de Telegram.

Solo presentación: aquí no se decide nada, solo se pinta lo que ya
calcularon los servicios. Los importes se escriben a la española
(1.234,50 €), que es como los va a leer quien usa el bot.
"""
from datetime import timedelta
from decimal import Decimal

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
        return f"Gasto anotado: {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"
    estado = "pendiente de cobro" if apunte.pendiente else "cobrado"
    return f"Trabajo anotado ({estado}): {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"


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
        "  Llamar al fontanero martes  → nota, sin dinero\n\n"
        "Cuando no puedas escribir, mándame una nota de voz: la escucho y\n"
        "la anoto igual.\n\n"
        "Comandos:\n"
        "  /hoy — resumen del día\n"
        "  /mes — resumen del mes\n"
        "  /trimestre — lo que llevas este trimestre\n"
        "  /cobrado <número> — marca un trabajo como cobrado\n"
        "  /borrar <número> — borra un apunte mal escrito\n"
        "  /agenda — lo que toca hoy\n"
        "  /manana — lo que toca mañana\n"
        "  /cita mañana 10:00 Cambiar grifo — apunta una cita\n"
        "      también vale: /cita 20 de septiembre a las 10am Ver la casa\n"
        "  /notas — el buzón de lo que no tiene fecha\n"
        "  /hecha <número> — marca una nota como cumplida\n"
        "  /habitos — marca los hábitos de hoy\n"
        "  /deben — quién te debe dinero\n"
        "  /cliente Ana Ruiz 600111222 — da de alta un cliente\n"
        "  /avisos on|off — resumen automático cada noche\n"
        "  /web — token para entrar en la web\n"
        "  /copia — te mando todo en un CSV, por si acaso\n\n"
        "Si algún día pierdes datos, reenvíame una de esas copias y vuelvo a "
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
    lineas.append("/hecha <número> cuando la cumplas. Ponerles fecha, desde la web.")
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
        f"No puedo restaurar ese fichero: {motivo}.\n\n"
        "Tiene que ser una de las copias que te mando yo (el CSV de /copia)."
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
