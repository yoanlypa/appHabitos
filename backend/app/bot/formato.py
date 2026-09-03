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
        "  /avisos on|off — resumen automático cada noche\n"
        "  /web — token para entrar en la web"
    )
