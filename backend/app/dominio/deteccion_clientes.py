"""Reconocer a un cliente dentro del texto de un apunte.

"Cambio de grifo Ana 120" tiene que acabar colgando de Ana sin que haya que
elegirla de una lista. Solo se reconoce a gente que ya está dada de alta:
adivinar que una palabra desconocida es una persona es imposible sin
equivocarse ("cambio de grifo cocina 120" — cocina no es nadie).

Cuando el nombre no basta para decidir (dos Anas), se devuelven las dos y
que elija quien escribió: un trabajo colgado de la Ana equivocada es peor
que un trabajo sin cliente.

Regla pura y sin base de datos, para poder probarla con casos sueltos.
"""
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidato:
    """Lo mínimo que hace falta para reconocer a alguien: su id y su nombre."""

    id: int
    nombre: str


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    return sin_tildes


def _palabras(texto: str) -> list[str]:
    return re.findall(r"[a-z0-9ñ]+", _normalizar(texto))


def buscar_clientes(texto: str, candidatos: list[Candidato]) -> list[Candidato]:
    """Los clientes mencionados en el texto.

    Devuelve una lista porque el resultado tiene tres lecturas distintas:
    vacía (nadie reconocido), uno solo (se asigna sin preguntar) o varios
    (hay que preguntar).
    """
    palabras = _palabras(texto)
    if not palabras:
        return []
    seguidas = " ".join(palabras)

    por_completo: list[Candidato] = []
    por_nombre_pila: list[Candidato] = []

    for candidato in candidatos:
        partes = _palabras(candidato.nombre)
        if not partes:
            continue
        # Nombres de una o dos letras dan demasiados falsos positivos.
        if len(partes[0]) < 3:
            continue

        if len(partes) > 1 and " ".join(partes) in seguidas:
            por_completo.append(candidato)
        elif partes[0] in palabras:
            por_nombre_pila.append(candidato)

    # Si alguien encaja por nombre y apellido, gana a quien solo comparte el
    # nombre de pila: "reforma de Ana Ruiz" no debe preguntar por Ana Pérez.
    return por_completo or por_nombre_pila
