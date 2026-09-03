"""Casos de uso de autenticación: generar y comprobar tokens de acceso a la web.

Sin usuario/contraseña — el bot de Telegram generará el token con `/web`
(fase `bot/`); hasta entonces, `generar_token()` se usa directamente.
"""
import secrets

from sqlalchemy.orm import Session

from app.dominio.models import TokenAcceso


def generar_token(db: Session, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(TokenAcceso(user_id=user_id, token=token))
    db.commit()
    return token


def usuario_por_token(db: Session, token: str) -> int | None:
    registro = db.query(TokenAcceso).filter(TokenAcceso.token == token).first()
    return registro.user_id if registro else None
