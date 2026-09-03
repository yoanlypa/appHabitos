"""Dependencias FastAPI compartidas: sesión de BD y usuario autenticado por token."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.nucleo.db import get_db
from app.servicios.auth import usuario_por_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user_id(
    credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> int:
    if credenciales is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "falta token de acceso")
    user_id = usuario_por_token(db, credenciales.credentials)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido")
    return user_id
