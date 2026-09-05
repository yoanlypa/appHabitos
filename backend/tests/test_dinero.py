"""El dinero, que es donde más caro sale equivocarse.

El test de `func.sum` está aquí porque ese fallo ya ocurrió: la lista de
clientes mostraba 9,80 € donde debía poner 980,50 €, cien veces menos,
porque el agregado ya venía en euros y se volvía a dividir entre 100.
"""
from decimal import Decimal

import sqlalchemy as sa

from app.servicios.apuntes import crear_apunte, listar_apuntes
from app.servicios.clientes import crear_cliente, ficha_cliente, listar_clientes
from tests.conftest import USUARIO


def test_el_importe_se_guarda_en_centimos_enteros(db):
    apunte = crear_apunte(db, USUARIO, "Cambio de grifo 120,45", origen="web")

    crudo = db.execute(
        sa.text("select importe from apuntes where id = :i"), {"i": apunte.id}
    ).scalar()
    assert crudo == 12045, "en la base tiene que haber céntimos, no euros"
    assert apunte.importe == Decimal("120.45")


def test_los_decimales_no_se_arrastran(db):
    """0,1 + 0,2 en coma flotante da 0,30000000000000004; en céntimos, 30."""
    crear_apunte(db, USUARIO, "Uno 0,10", origen="web")
    crear_apunte(db, USUARIO, "Otro 0,20", origen="web")

    centimos = list(db.execute(sa.text("select importe from apuntes")).scalars())
    assert centimos == [10, 20]
    assert sum(centimos) == 30, "30 céntimos exactos, sin cola de decimales"

    # Y al leerlos de vuelta, euros exactos.
    total_euros = sum(a.importe for a in listar_apuntes(db, USUARIO))
    assert total_euros == Decimal("0.30")


def test_la_deuda_de_la_lista_coincide_con_la_de_la_ficha(db):
    """Este desacuerdo fue el que delató el error de escala de cien veces."""
    cliente = crear_cliente(db, USUARIO, "Ana Ruiz")
    crear_apunte(db, USUARIO, "pendiente Reforma 980,50", origen="web", cliente_id=cliente.id)

    de_la_lista = listar_clientes(db, USUARIO)[0].debe
    de_la_ficha = ficha_cliente(db, USUARIO, cliente.id).debe

    assert de_la_lista == Decimal("980.50")
    assert de_la_lista == de_la_ficha


def test_el_id_de_telegram_no_cabe_en_un_entero_de_32_bits(db):
    """Por esto `user_id` es BigInteger: el id real de Yoa lo triplica."""
    assert USUARIO > 2_147_483_647

    apunte = crear_apunte(db, USUARIO, "Trabajo 50", origen="bot")
    db.refresh(apunte)
    assert apunte.user_id == USUARIO
