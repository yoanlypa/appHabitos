"""Motor y sesiones de base de datos.

SQLite en local y en Railway, Postgres si se cambia `DATABASE_URL` — este
módulo no debe suponer un motor concreto más allá de configurar SQLite en
modo WAL cuando toque.
"""
from contextlib import contextmanager

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.nucleo.config import DATABASE_URL

_es_sqlite = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if _es_sqlite else {},
)

if _es_sqlite:
    @event.listens_for(engine, "connect")
    def _activar_wal(conexion_dbapi, _registro_conexion):
        # La API y el bot leen/escriben la misma base a la vez; sin WAL se
        # bloquean entre ellos.
        cursor = conexion_dbapi.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# SQLite no sabe hacer ALTER TABLE de casi nada, así que Alembic recrea la
# tabla entera para cambiarla — y para eso necesita poder nombrar cada
# restricción. Sin esta convención, añadir una clave ajena revienta con
# "Constraint must have a name".
_CONVENCION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Base = declarative_base(metadata=MetaData(naming_convention=_CONVENCION))


def crear_tablas() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependencia de FastAPI (`Depends(get_db)`)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def sesion() -> Session:
    """Sesión para quien no es FastAPI — el bot, y los scripts de prueba."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
