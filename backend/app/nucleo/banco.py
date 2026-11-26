"""Hablar con Enable Banking: el agregador que lee la cuenta del banco (PSD2).

No sabe qué es un gasto ni de quién es la cuenta: firma las peticiones,
llama y devuelve lo que contesta. Qué movimiento es qué lo decide
`dominio/banco.py`, y qué se guarda, `servicios/banco.py`.

Cada petición lleva un JWT firmado con la clave privada de la aplicación
(RS256, `kid` = Application ID). La clave está en Railway y no sale de ahí.

Asíncrono por lo mismo que la voz y el correo: la API y el bot comparten
proceso, y una llamada lenta en bloqueante dejaría la web colgada.
"""
import re
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


_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]+)-----(.*?)-----END \1-----", re.S)


def _bloque(texto: str) -> re.Match | None:
    """El bloque BEGIN…END de la clave privada; si no hay, el primero que haya.

    Algunos .pem traen la clave y el certificado juntos: el que firma es la clave.
    """
    bloques = list(_PEM.finditer(texto))
    privados = [b for b in bloques if "PRIVATE KEY" in b.group(1)]
    return (privados or bloques or [None])[0]


def normalizar_pem(texto: str) -> str:
    """La clave tal como la deja Railway, vuelta a dejar como un .pem.

    Pegada en la casilla de una variable, la clave llega de muchas formas: en
    una sola línea con las líneas unidas por espacios, con "\\n" escritos,
    entre comillas o con los saltos de Windows. El contenido es el mismo;
    solo cambia el formato. Se saca lo que hay entre BEGIN y END, se quitan
    todos los espacios y se vuelve a partir en líneas de 64, como un .pem.
    """
    limpio = (texto or "").strip().strip('"').strip("'").replace("\\n", "\n").replace("\r", "")
    trozo = _bloque(limpio)
    if not trozo:
        return limpio
    tipo, cuerpo = trozo.group(1).strip(), re.sub(r"\s+", "", trozo.group(2))
    lineas = [cuerpo[i : i + 64] for i in range(0, len(cuerpo), 64)]
    return f"-----BEGIN {tipo}-----\n" + "\n".join(lineas) + f"\n-----END {tipo}-----\n"


def que_le_pasa(texto: str) -> str:
    """Por qué no vale la clave, sin enseñar nada de ella."""
    limpio = (texto or "").strip()
    trozo = _bloque(normalizar_pem(limpio))
    if not trozo:
        if "BEGIN" in limpio and "END" not in limpio:
            return "está cortada: falta la línea -----END … -----"
        return "no encuentro la línea -----BEGIN … -----: pega el .pem entero, de BEGIN a END"
    tipo = trozo.group(1).strip()
    if "CERTIFICATE" in tipo or "PUBLIC" in tipo:
        return f"has pegado {tipo.lower()}, que es la parte pública; hace falta la clave PRIVADA (BEGIN PRIVATE KEY)"
    if "ENCRYPTED" in tipo:
        return "la clave está protegida con contraseña; hace falta la que se descargó sin contraseña"
    largo = len(re.sub(r"\s+", "", trozo.group(2)))
    return f"es una {tipo.lower()} pero no se puede leer (tiene {largo} caracteres): ¿le falta algún trozo?"


def hay_banco() -> bool:
    return bool(ENABLE_BANKING_APP_ID and ENABLE_BANKING_CLAVE.strip())


def _cabeceras() -> dict:
    if not hay_banco():
        raise BancoNoDisponible("faltan ENABLE_BANKING_APP_ID y ENABLE_BANKING_CLAVE en el entorno")
    ahora = int(datetime.now(timezone.utc).timestamp())
    try:
        token = jwt.encode(
            {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": ahora, "exp": ahora + 3600},
            normalizar_pem(ENABLE_BANKING_CLAVE),
            algorithm="RS256",
            headers={"kid": ENABLE_BANKING_APP_ID},
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise BancoNoDisponible(
            f"la clave ENABLE_BANKING_CLAVE no se puede leer: {que_le_pasa(ENABLE_BANKING_CLAVE)}"
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
