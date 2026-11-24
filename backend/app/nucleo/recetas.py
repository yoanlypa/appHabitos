"""Pregunta al modelo qué se puede cocinar con lo que hay en casa.

Es la misma OPENAI_API_KEY que la voz y los tickets, pero solo texto: una
consulta cuesta una fracción de céntimo. Se pide JSON para que la web y el
bot pinten lo mismo, y se filtra lo que vuelve: una receta sin nombre o sin
pasos no se enseña.
"""
import json

import httpx

from app.nucleo.config import MODELO_RECETAS, OPENAI_API_KEY

_URL = "https://api.openai.com/v1/chat/completions"

_INSTRUCCIONES = """Eres un cocinero casero español. Te dan lo que hay en una casa
y propones platos sencillos y normales para el día a día de una familia.

Reglas:
- Prioriza platos que se hagan SOLO con lo que hay, más básicos de despensa
  que casi todas las casas tienen (sal, aceite, agua, pimienta, ajo).
- Si un plato necesita algo que no está, dilo en "falta" (pocas cosas).
- Pasos cortos y claros, de 3 a 7. Tiempo realista en minutos.
- No inventes ingredientes que no se han dicho para ponerlos en "usa".
- Si te dicen preferencias (rápido, para niños, sin horno...), respétalas.

Devuelve SOLO un JSON: {"recetas": [{"nombre": str, "minutos": int,
"usa": [str], "falta": [str], "pasos": [str]}]} con 3 o 4 recetas."""


class RecetasNoDisponibles(RuntimeError):
    """No hay clave para preguntar al modelo."""


class ErrorDeRecetas(RuntimeError):
    """El servicio falló o devolvió algo que no se entiende."""


def hay_recetas() -> bool:
    return bool(OPENAI_API_KEY)


def _lista_de_textos(valor) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if isinstance(v, (str, int, float)) and str(v).strip()][:15]


def limpiar(datos: dict) -> list[dict]:
    """Se queda con las recetas que tienen nombre y pasos; lo demás se tira."""
    recetas = []
    for r in datos.get("recetas") or []:
        if not isinstance(r, dict):
            continue
        nombre = str(r.get("nombre") or "").strip()
        pasos = _lista_de_textos(r.get("pasos"))
        if not nombre or not pasos:
            continue
        try:
            minutos = int(r.get("minutos"))
            minutos = minutos if 0 < minutos <= 600 else None
        except (TypeError, ValueError):
            minutos = None
        recetas.append({
            "nombre": nombre[:120],
            "minutos": minutos,
            "usa": _lista_de_textos(r.get("usa")),
            "falta": _lista_de_textos(r.get("falta")),
            "pasos": pasos,
        })
    return recetas[:5]


async def pedir_recetas(ingredientes: list[str], preferencias: str = "") -> list[dict]:
    if not OPENAI_API_KEY:
        raise RecetasNoDisponibles("falta OPENAI_API_KEY en el entorno")
    pregunta = "Lo que hay en casa: " + (", ".join(ingredientes) if ingredientes else "(no han dicho nada)")
    if preferencias.strip():
        pregunta += f"\nPreferencias o más cosas que hay: {preferencias.strip()}"
    cuerpo = {
        "model": MODELO_RECETAS,
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": _INSTRUCCIONES},
            {"role": "user", "content": pregunta},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=60) as cliente:
            respuesta = await cliente.post(_URL, headers={"Authorization": f"Bearer {OPENAI_API_KEY}"}, json=cuerpo)
    except httpx.HTTPError as exc:
        raise ErrorDeRecetas(f"no se pudo llamar al servicio: {exc}") from exc
    if respuesta.status_code != 200:
        raise ErrorDeRecetas(f"el servicio respondió {respuesta.status_code}: {respuesta.text[:200]}")
    try:
        datos = json.loads(respuesta.json()["choices"][0]["message"]["content"])
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise ErrorDeRecetas("el servicio devolvió algo que no es JSON") from exc
    if not isinstance(datos, dict):
        raise ErrorDeRecetas("el servicio devolvió algo que no es un objeto")
    return limpiar(datos)
