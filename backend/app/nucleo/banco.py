"""Hablar con Enable Banking: el agregador que lee la cuenta del banco (PSD2).

No sabe qué es un gasto ni de quién es la cuenta: firma las peticiones,
llama y devuelve lo que contesta. Qué movimiento es qué lo decide
`dominio/banco.py`, y qué se guarda, `servicios/banco.py`.

Cada petición lleva un JWT firmado con la clave privada de la aplicación
(RS256, `kid` = Application ID). La clave está en Railway y no sale de ahí.

Asíncrono por lo mismo que la voz y el correo: la API y el bot comparten
proceso, y una llamada lenta en bloqueante dejaría la web colgada.
"""
from datetime import date, datetime, timezone

import httpx
import jwt

from app.nucleo.config import ENABLE_BANKING_APP_ID, ENABLE_BANKING_CLAVE

API = "https://api.enablebanking.com"
# Por si el banco pagina sin fin: con 30 días de movimientos sobra.
_PAGINAS_MAXIMAS = 20


class BancoNoDisponible(RuntimeError):
    """Faltan el Application ID o la clave: hay que configurarlos en Railway."""


class ErrorDeBanco(RuntimeError):
    """Enable Banking o el banco no aceptaron la petición."""


def hay_banco() -> bool:
    return bool(ENABLE_BANKING_APP_ID and ENABLE_BANKING_CLAVE)


def _cabeceras() -> dict:
    if not hay_banco():
        raise BancoNoDisponible("faltan ENABLE_BANKING_APP_ID y ENABLE_BANKING_CLAVE en el entorno")
    ahora = int(datetime.now(timezone.utc).timestamp())
    try:
        token = jwt.encode(
            {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": ahora, "exp": ahora + 3600},
            ENABLE_BANKING_CLAVE,
            algorithm="RS256",
            headers={"kid": ENABLE_BANKING_APP_ID},
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise BancoNoDisponible(
            "la clave ENABLE_BANKING_CLAVE no se puede leer: pega el .pem entero, de BEGIN a END"
        ) from exc
    return {"Authorization": f"Bearer {token}"}


async def _pedir(metodo: str, ruta: str, **kwargs) -> dict:
    cabeceras = _cabeceras()
    try:
        async with httpx.AsyncClient(timeout=60) as cliente:
            respuesta = await cliente.request(metodo, f"{API}{ruta}", headers=cabeceras, **kwargs)
    except httpx.HTTPError as exc:
        raise ErrorDeBanco(f"no se ha podido hablar con Enable Banking: {exc}") from exc
    if respuesta.status_code >= 400:
        try:
            detalle = respuesta.json().get("message") or respuesta.text
        except ValueError:
            detalle = respuesta.text
        raise ErrorDeBanco(f"{respuesta.status_code}: {detalle}"[:300])
    return respuesta.json()


async def bancos(pais: str) -> list[dict]:
    return (await _pedir("GET", "/aspsps", params={"country": pais})).get("aspsps", [])


async def autorizar(nombre: str, pais: str, hasta: datetime, estado: str, vuelta: str) -> str:
    """El enlace donde se da permiso en el banco. Devuelve la URL."""
    datos = await _pedir(
        "POST",
        "/auth",
        json={
            "access": {"valid_until": hasta.isoformat()},
            "aspsp": {"name": nombre, "country": pais},
            "state": estado,
            "redirect_url": vuelta,
            "psu_type": "personal",
        },
    )
    return datos["url"]


async def crear_sesion(codigo: str) -> dict:
    return await _pedir("POST", "/sessions", json={"code": codigo})


async def movimientos(cuenta_uid: str, desde: date) -> list[dict]:
    todos: list[dict] = []
    siguiente = None
    for _ in range(_PAGINAS_MAXIMAS):
        params = {"date_from": desde.isoformat()}
        if siguiente:
            params["continuation_key"] = siguiente
        pagina = await _pedir("GET", f"/accounts/{cuenta_uid}/transactions", params=params)
        todos += pagina.get("transactions") or []
        siguiente = pagina.get("continuation_key")
        if not siguiente:
            break
    return todos
