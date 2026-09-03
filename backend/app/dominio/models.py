"""Modelos SQLAlchemy. Reglas de forma de los datos, nada de HTTP ni Telegram.

`Centimos` es el porqué de este archivo: guarda importes en céntimos
(INTEGER) para no arrastrar errores de redondeo de coma flotante
(0.1 + 0.2 != 0.3), pero los expone en euros (Decimal) al resto del código.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    TypeDecorator,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.nucleo.db import Base


class Centimos(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        euros = value if isinstance(value, Decimal) else Decimal(str(value))
        return int((euros * 100).to_integral_value(rounding=ROUND_HALF_UP))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value) / 100


class Apunte(Base):
    __tablename__ = "apuntes"

    id = Column(Integer, primary_key=True)
    # BigInteger porque los ids de Telegram ya superan el INT de 32 bits de
    # Postgres; en SQLite daría igual, pero el motor puede cambiar.
    user_id = Column(BigInteger, nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    tipo = Column(String, nullable=False)  # "trabajo" | "gasto"
    concepto = Column(String, nullable=False)
    importe = Column(Centimos, nullable=False)  # euros en Python, céntimos en BD
    pendiente = Column(Boolean, nullable=False, default=False)  # solo aplica a tipo="trabajo"
    origen = Column(String, nullable=False)  # "web" | "bot"
    creado = Column(DateTime(timezone=True), server_default=func.now())
    # Opcional a propósito: apuntar rápido desde el móvil no puede exigir
    # elegir cliente. Se asocia después, o nunca.
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)

    cliente = relationship("Cliente", back_populates="apuntes")


class Ajuste(Base):
    __tablename__ = "ajustes"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, unique=True, index=True)
    avisos_activos = Column(Boolean, nullable=False, default=True)


class TokenAcceso(Base):
    __tablename__ = "tokens_acceso"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    token = Column(String, nullable=False, unique=True, index=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())


class Cliente(Base):
    """La gente para la que trabajas.

    El nombre no es único a propósito: puede haber dos Anas, y obligar a
    distinguirlas al darlas de alta estorbaría más que ayuda.
    """

    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    nombre = Column(String, nullable=False, index=True)
    telefono = Column(String, nullable=True)
    direccion = Column(String, nullable=True)
    notas = Column(Text, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())

    apuntes = relationship("Apunte", back_populates="cliente")
    citas = relationship("Cita", back_populates="cliente")


class Cita(Base):
    """Una visita en la agenda.

    La hora es opcional: hay avisos que son "el martes paso por allí" sin
    hora cerrada, y obligar a poner una obligaría a inventársela.
    """

    __tablename__ = "citas"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    hora = Column(Time, nullable=True)
    titulo = Column(String, nullable=False)
    direccion = Column(String, nullable=True)
    notas = Column(Text, nullable=True)
    hecha = Column(Boolean, nullable=False, default=False)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)

    cliente = relationship("Cliente", back_populates="citas")
