"""Qué va a la gestoría y qué se queda en las cuentas de Yoa.

No todo lo que Yoa trabaja lo factura él: hay trabajos que factura otra
empresa, que le paga por contrato. En la app está todo junto, porque es su
día a día, pero a la gestoría solo va lo suyo: las facturas que emite y los
gastos que les corresponden. Mandar de más es declarar gastos de un ingreso
que no es suyo; mandar de menos, perder un gasto deducible.

La regla, en un solo sitio para que el listado, el CSV y el PDF no puedan
decidir cosas distintas:

- Un **trabajo** va si está marcado como facturado.
- Un **gasto de un trabajo** va si ese trabajo está facturado. No se marca
  aparte: sigue a su trabajo, y si mañana se factura, el gasto entra solo.
- Un **gasto suelto** (gasolina, el seguro, la cuota de autónomos) va si
  se ha marcado a mano. Nunca se decide por él: aquí no se sabe qué es
  deducible.
"""
import re


def va_a_gestoria(
    tipo: str,
    facturado: bool,
    para_gestoria: bool,
    trabajo_facturado: bool | None,
) -> bool:
    """`trabajo_facturado` es None si el gasto no cuelga de ningún trabajo."""
    if tipo == "trabajo":
        return bool(facturado)
    if tipo != "gasto":
        return False  # una nota no es dinero
    if trabajo_facturado is not None:
        return trabajo_facturado
    return bool(para_gestoria)


# "para la gestoría", "para gestoria", "para el gestor"... o el mensaje entero
# es solo esa palabra. No basta con que aparezca "gestoría": "Factura
# gestoría octubre" es el concepto de un gasto, no una instrucción, y
# quitarle la palabra lo dejaría en "Factura octubre".
_RE_PARA_GESTORIA = re.compile(
    r"\bpara\s+(?:la\s+|el\s+|mi\s+)?gestor(?:[ií]a)?\b", re.IGNORECASE
)
_RE_SOLO_GESTORIA = re.compile(r"^\s*(?:la\s+)?gestor(?:[ií]a)?\s*$", re.IGNORECASE)


def marca_gestoria(texto: str | None) -> tuple[bool, str]:
    """"para la gestoría" en el mensaje de un ticket: ese gasto va a la gestoría.

    Se quita del texto para que no acabe en el concepto.
    """
    if not texto:
        return False, ""
    if _RE_SOLO_GESTORIA.match(texto):
        return True, ""
    if not _RE_PARA_GESTORIA.search(texto):
        return False, texto
    return True, " ".join(_RE_PARA_GESTORIA.sub(" ", texto).split())
