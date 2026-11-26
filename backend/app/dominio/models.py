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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from app.dominio.gestoria import va_a_gestoria
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
    # "nota" es lo que se dicta sin importe ("llamar a Ana el martes"): va
    # con importe 0 y los resúmenes no la suman.
    tipo = Column(String, nullable=False)  # "trabajo" | "gasto" | "nota"
    concepto = Column(String, nullable=False)
    importe = Column(Centimos, nullable=False)  # euros en Python, céntimos en BD
    pendiente = Column(Boolean, nullable=False, default=False)  # solo aplica a tipo="trabajo"
    # Solo aplica a tipo="nota". Una nota cumplida no es una nota equivocada:
    # se marca y sale del buzón, pero se puede seguir viendo y deshacer.
    hecha = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    origen = Column(String, nullable=False)  # "web" | "bot"
    creado = Column(DateTime(timezone=True), server_default=func.now())
    # Opcional a propósito: apuntar rápido desde el móvil no puede exigir
    # elegir cliente. Se asocia después, o nunca.
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)

    # El trabajo (la obra) al que pertenece: un cobro, un gasto o una nota.
    trabajo_id = Column(Integer, ForeignKey("trabajos.id"), nullable=True, index=True)
    # Solo aplica a un cobro o gasto suelto (sin trabajo): marcado a mano
    # para la gestoría. Los de un trabajo siguen a su trabajo.
    para_gestoria = Column(Boolean, nullable=False, default=False, server_default=text("0"))

    cliente = relationship("Cliente", back_populates="apuntes")
    # La foto del ticket, si el gasto salió de escanearlo. Una por apunte.
    factura = relationship("Factura", back_populates="apunte", uselist=False)
    trabajo = relationship("Trabajo", back_populates="apuntes")

    @property
    def gestoria(self) -> bool:
        """Si este apunte sale en lo que se manda a la gestoría."""
        return va_a_gestoria(
            self.tipo,
            self.para_gestoria,
            self.trabajo.facturado if self.trabajo is not None else None,
            self.factura_emitida,
        )

    @property
    def trabajo_titulo(self) -> str | None:
        return self.trabajo.titulo if self.trabajo is not None else None

    @property
    def factura_id(self) -> int | None:
        return self.factura.id if self.factura else None

    @property
    def factura_emitida(self) -> bool:
        """Si cuelga de una factura que emitió Yoa (no de un ticket de compra)."""
        return bool(self.factura and self.factura.emitida)


class Ajuste(Base):
    __tablename__ = "ajustes"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, unique=True, index=True)
    avisos_activos = Column(Boolean, nullable=False, default=True)
    # A dónde mandar también por correo los avisos de citas. Vacío: solo Telegram.
    # En la base y no en una variable de Railway: el repo es público y cada
    # usuario tiene la suya.
    correo = Column(String, nullable=True)


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

    `fecha_fin` también: una reforma de tres días es UNA cosa, no tres citas
    sueltas que haya que marcar y borrar una a una. Vacía significa que
    empieza y acaba el mismo día, que es el caso normal.
    """

    __tablename__ = "citas"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)  # el día, o el primero
    fecha_fin = Column(Date, nullable=True, index=True)  # último día, incluido
    hora = Column(Time, nullable=True)
    titulo = Column(String, nullable=False)
    direccion = Column(String, nullable=True)
    notas = Column(Text, nullable=True)
    hecha = Column(Boolean, nullable=False, default=False)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)
    # El día para el que ya se mandó el recordatorio de ese mismo día. Un
    # reinicio no lo repite, y si la cita se mueve a otro día vuelve a avisar.
    avisada_el = Column(Date, nullable=True)
    # El trabajo al que pertenece la cita, si es de uno.
    trabajo_id = Column(Integer, ForeignKey("trabajos.id"), nullable=True, index=True)

    cliente = relationship("Cliente", back_populates="citas")
    trabajo = relationship("Trabajo", back_populates="citas")


class Habito(Base):
    """Algo que se quiere hacer con regularidad: beber agua, entrenar.

    `dias` son los días de la semana en que toca, como texto de dígitos
    ("01234" = de lunes a viernes, 0 es lunes). Un día que no toca no rompe
    la racha. Las reglas están en `dominio/habitos.py`.

    `inicio` es desde cuándo cuenta: los días de antes no son fallos.

    `recordar_a` es opcional. `recordado_el` guarda el último día en que se
    mandó el recordatorio en la base y no en memoria: si el proceso se
    reinicia a media mañana, no lo vuelve a mandar.
    """

    __tablename__ = "habitos"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    nombre = Column(String, nullable=False)
    dias = Column(String, nullable=False, default="0123456")
    inicio = Column(Date, nullable=False)
    recordar_a = Column(Time, nullable=True)
    recordado_el = Column(Date, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())

    hechos = relationship(
        "HabitoHecho", back_populates="habito", cascade="all, delete-orphan"
    )


class HabitoHecho(Base):
    """Un día en que se cumplió. El día que no se hizo no tiene fila.

    Uno por hábito y día: marcar dos veces el mismo día no puede contar doble
    en la racha.
    """

    __tablename__ = "habitos_hechos"
    __table_args__ = (UniqueConstraint("habito_id", "fecha"),)

    id = Column(Integer, primary_key=True)
    habito_id = Column(Integer, ForeignKey("habitos.id"), nullable=False, index=True)
    fecha = Column(Date, nullable=False)

    habito = relationship("Habito", back_populates="hechos")


class Factura(Base):
    """La foto de un ticket o factura escaneado.

    La imagen vive en disco (`nucleo/archivos.py`) y aquí solo su ruta
    relativa. `apunte_id` va vacío entre que se escanea y se confirma el
    gasto: leer la foto y guardarla son dos pasos, porque lo leído se
    enseña antes de anotarlo.
    """

    __tablename__ = "facturas"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    apunte_id = Column(Integer, ForeignKey("apuntes.id"), nullable=True, unique=True)
    ruta = Column(String, nullable=False)
    mime = Column(String, nullable=False)
    tamano = Column(Integer, nullable=False)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    # Todo lo que se leyó del ticket (líneas, CIF, número, base, forma de
    # pago...), como JSON. Texto y no un tipo JSON del motor, para que SQLite
    # y Postgres lo guarden igual.
    datos = Column(Text, nullable=True)
    # Las esquinas del papel que vio el modelo, para enderezar el PDF.
    esquinas = Column(Text, nullable=True)
    # True si la factura la emite Yoa a un cliente (cuelga de un trabajo, es
    # dinero que entra); False si es un ticket o factura de compra (un gasto).
    emitida = Column(Boolean, nullable=False, default=False, server_default=text("0"))

    apunte = relationship("Apunte", back_populates="factura")


class EmisorPropio(Base):
    """Un emisor que Yoa ha dicho que es él, para reconocer sus facturas solo.

    Sus facturas salen siempre con el mismo formato, pero a nombre de la
    persona y no de la marca, y la variable `NOMBRES_PROPIOS` puede faltar en
    Railway. Cada vez que corrige una a mano (/emitida, o "mía" en el
    mensaje) se guarda aquí el NIF y el nombre leídos tal como los lee la IA,
    y la siguiente igual entra como suya. Va en la base y no en el código
    porque el repo es público.
    """

    __tablename__ = "emisores_propios"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    nif = Column(String, nullable=True)
    nombre = Column(String, nullable=True)
    # La cuenta que sale en sus facturas para que le paguen: la delata aunque
    # la IA cruce emisor y cliente.
    iban = Column(String, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())


class Trabajo(Base):
    """Una obra: la ficha que junta todo lo de un trabajo.

    Sus cobros, sus gastos, sus notas y sus citas cuelgan de ella. Es lo que
    Yoa abre para ver cómo va una obra, como una página de Notion.

    `facturado` dice si la factura la hace Yoa: si no (la factura otra empresa,
    que le paga por contrato), ni sus cobros ni sus gastos van a la gestoría.
    `resena` es si el cliente dejó reseña: pedirla al acabar es fácil de olvidar.
    """

    __tablename__ = "trabajos"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    titulo = Column(String, nullable=False)
    descripcion = Column(Text, nullable=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=True, index=True)
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    facturado = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    resena = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    creado = Column(DateTime(timezone=True), server_default=func.now())

    cliente = relationship("Cliente")
    apuntes = relationship("Apunte", back_populates="trabajo", order_by="Apunte.fecha")
    citas = relationship("Cita", back_populates="trabajo", order_by="Cita.fecha")


# --- Casa -------------------------------------------------------------------
#
# El dinero y la compra del hogar, compartidos entre varias personas. Van en
# tablas propias y no en `apuntes` a propósito: así ningún resumen del
# negocio, ni el trimestre, ni la gestoría pueden contar un gasto del súper.


class Hogar(Base):
    __tablename__ = "hogares"

    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False, default="Casa")
    creado = Column(DateTime(timezone=True), server_default=func.now())

    miembros = relationship("MiembroHogar", back_populates="hogar", order_by="MiembroHogar.id")


class MiembroHogar(Base):
    """Quién vive en la casa. Un `user_id` es de una sola casa.

    El titular es quien la creó (Yoa). Los demás entran con una invitación y
    solo ven Casa: el negocio no es cosa suya. Quien entra solo por la web
    no tiene id de Telegram y recibe uno negativo, que nunca choca con uno
    de verdad.
    """

    __tablename__ = "hogar_miembros"

    id = Column(Integer, primary_key=True)
    hogar_id = Column(Integer, ForeignKey("hogares.id"), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, unique=True)
    nombre = Column(String, nullable=False)
    titular = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    # Cómo paga casi siempre: así un "45 súper" sin decir nada sale de su
    # cartera o no. En esta casa se paga mucho en efectivo: empieza en sí.
    efectivo = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    creado = Column(DateTime(timezone=True), server_default=func.now())

    hogar = relationship("Hogar", back_populates="miembros")


class InvitacionHogar(Base):
    """Un código para entrar en una casa. Vale una vez y caduca a los 7 días."""

    __tablename__ = "hogar_invitaciones"

    id = Column(Integer, primary_key=True)
    hogar_id = Column(Integer, ForeignKey("hogares.id"), nullable=False, index=True)
    codigo = Column(String, nullable=False, unique=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    usada_por = Column(BigInteger, nullable=True)


class GastoCasa(Base):
    """Un gasto de la casa: quién lo pagó, cuándo, en qué y cuánto."""

    __tablename__ = "gastos_casa"

    id = Column(Integer, primary_key=True)
    hogar_id = Column(Integer, ForeignKey("hogares.id"), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    concepto = Column(String, nullable=False)
    importe = Column(Centimos, nullable=False)
    categoria = Column(String, nullable=False, default="Otros")
    origen = Column(String, nullable=False, default="web")
    # Pagado en efectivo: sale de la cartera de quien lo pagó.
    efectivo = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    creado = Column(DateTime(timezone=True), server_default=func.now())


class MovimientoCartera(Base):
    """Lo que entra en la cartera de alguien, o lo que contó que le quedaba.

    El efectivo no deja rastro: en vez de apuntar cada billete, se apunta lo
    que entra ("saco 200") y de vez en cuando se cuenta lo que queda. Lo que
    falta y nadie apuntó se anota como "Efectivo sin detallar" (`gasto_id`),
    así el total del mes es verdadero aunque no se sepa en qué se fue.
    """

    __tablename__ = "cartera_movimientos"

    id = Column(Integer, primary_key=True)
    hogar_id = Column(Integer, ForeignKey("hogares.id"), nullable=False, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    fecha = Column(Date, nullable=False)
    tipo = Column(String, nullable=False)  # "entrada" | "recuento"
    importe = Column(Centimos, nullable=False)
    gasto_id = Column(Integer, ForeignKey("gastos_casa.id"), nullable=True)
    # El último gasto que ya existía al contar: lo del mismo día apuntado
    # después del recuento cuenta para el siguiente, no para este.
    hasta_gasto_id = Column(Integer, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())


class ArticuloCompra(Base):
    """Una cosa de la lista de la compra o de la despensa.

    Es la misma fila en los dos sitios: `hay` falso es que falta (lista de la
    compra); al comprarla pasa a `hay` (despensa, que es lo que se usa para
    pensar qué hacer de comer), y "se acabó" la devuelve a la lista con un
    toque, sin volver a escribirla.
    """

    __tablename__ = "compra_articulos"

    id = Column(Integer, primary_key=True)
    hogar_id = Column(Integer, ForeignKey("hogares.id"), nullable=False, index=True)
    texto = Column(String, nullable=False)
    hay = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    anadido_por = Column(BigInteger, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())
    cambiado = Column(DateTime(timezone=True), server_default=func.now())


class ConexionBanco(Base):
    """El permiso para leer una cuenta del banco (PSD2, vía Enable Banking).

    Se crea "pendiente" al pedir el enlace, con un `estado` aleatorio que
    vuelve del banco y dice de quién es la vuelta (la página de vuelta no
    lleva token). Al volver pasa a "activa" con su sesión; la anterior de esa
    persona queda "sustituida". El permiso caduca (`valido_hasta`): lo pone
    el banco, no la app, y entonces hay que volver a darlo.
    """

    __tablename__ = "conexiones_banco"

    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    banco = Column(String, nullable=False)
    estado = Column(String, nullable=False, default="pendiente")  # pendiente | activa | sustituida
    clave_vuelta = Column(String, nullable=True, unique=True)
    sesion = Column(String, nullable=True)
    valido_hasta = Column(DateTime(timezone=True), nullable=True)
    # Las cuentas que dejó ver el banco, en JSON: uid, nombre, tipo, final del IBAN.
    cuentas = Column(Text, nullable=True)
    creado = Column(DateTime(timezone=True), server_default=func.now())
