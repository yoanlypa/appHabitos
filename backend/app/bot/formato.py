"""Cómo se ve un apunte o un resumen en un mensaje de Telegram.

Solo presentación: aquí no se decide nada, solo se pinta lo que ya
calcularon los servicios. Los importes se escriben a la española
(1.234,50 €), que es como los va a leer quien usa el bot.
"""
from decimal import Decimal

from app.dominio.models import Apunte
from app.servicios.resumen import ResumenPeriodo


def euros(importe: Decimal) -> str:
    # Se formatea al estilo inglés y se intercambian los separadores, que es
    # más corto y fiable que depender del locale del sistema.
    entero_y_decimales = f"{importe:,.2f}"
    return entero_y_decimales.replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def apunte_creado(apunte: Apunte) -> str:
    if apunte.tipo == "gasto":
        return f"Gasto anotado: {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"
    estado = "pendiente de cobro" if apunte.pendiente else "cobrado"
    return f"Trabajo anotado ({estado}): {apunte.concepto} — {euros(apunte.importe)}  (#{apunte.id})"


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
        "  -45 gasolina                → gasto\n\n"
        "Comandos:\n"
        "  /hoy — resumen del día\n"
        "  /mes — resumen del mes\n"
        "  /cobrado <número> — marca un trabajo como cobrado\n"
        "  /agenda — lo que toca hoy\n"
        "  /manana — lo que toca mañana\n"
        "  /cita mañana 10:00 Cambiar grifo — apunta una cita\n"
        "  /deben — quién te debe dinero\n"
        "  /cliente Ana Ruiz 600111222 — da de alta un cliente\n"
        "  /avisos on|off — resumen automático cada noche\n"
        "  /web — token para entrar en la web"
    )


def cita_creada(cita) -> str:
    cuando = cita.fecha.strftime("%d/%m")
    hora = cita.hora.strftime(" a las %H:%M") if cita.hora else ""
    quien = f" — {cita.cliente.nombre}" if cita.cliente else ""
    return f"Apuntado para el {cuando}{hora}: {cita.titulo}{quien}"


def lista_citas(titulo: str, citas: list) -> str:
    if not citas:
        return f"{titulo}\nNada apuntado."
    lineas = [titulo]
    for c in citas:
        hora = c.hora.strftime("%H:%M") if c.hora else "  ·  "
        marca = "✓ " if c.hecha else ""
        donde = f" ({c.direccion})" if c.direccion else ""
        quien = f" — {c.cliente.nombre}" if c.cliente else ""
        lineas.append(f"{hora}  {marca}{c.titulo}{quien}{donde}")
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
