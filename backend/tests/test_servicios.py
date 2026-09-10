"""Los casos de uso: apuntes, clientes, agenda y avisos.

Cubren sobre todo dos cosas que importan más que el camino feliz: que un
usuario no pueda tocar los datos de otro, y que borrar nunca se lleve por
delante dinero apuntado.
"""
from datetime import date, time, timedelta
from decimal import Decimal

import pytest

from app.dominio.parsing import TextoNoInterpretable
from app.servicios.agenda import (
    CitaNoEncontrada,
    citas_del_dia,
    crear_cita,
    marcar_hecha,
    proximas_citas,
)
from app.servicios.apuntes import (
    ApunteNoEncontrado,
    actualizar_apunte,
    anotar,
    borrar_apunte,
    crear_apunte,
    listar_apuntes,
    marcar_cobrado,
)
from app.servicios.avisos import activar_avisos, avisos_activos, destinatarios_del_aviso
from app.servicios.clientes import (
    ClienteNoEncontrado,
    borrar_cliente,
    crear_cliente,
    ficha_cliente,
    pendientes_de_cobro,
)
from app.servicios.resumen import resumen_dia
from tests.conftest import USUARIO

OTRO = 111222333


class TestApuntes:
    def test_marcar_cobrado_cambia_el_resumen(self, db):
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")
        pendiente = crear_apunte(db, USUARIO, "pendiente Reforma 980", origen="bot")
        crear_apunte(db, USUARIO, "-45,50 gasolina", origen="web")

        antes = resumen_dia(db, USUARIO)
        assert (antes.cobrado, antes.pendiente, antes.gastos) == (
            Decimal("120"),
            Decimal("980"),
            Decimal("45.50"),
        )
        assert antes.neto == Decimal("74.50")

        marcar_cobrado(db, USUARIO, pendiente.id)

        despues = resumen_dia(db, USUARIO)
        assert despues.cobrado == Decimal("1100")
        assert despues.pendiente == Decimal("0")

    def test_borrar_un_apunte_mal_escrito(self, db):
        """El 1200 que iba a ser 120."""
        malo = crear_apunte(db, USUARIO, "Cambio de grifo 1200", origen="bot")
        borrar_apunte(db, USUARIO, malo.id)

        assert listar_apuntes(db, USUARIO) == []
        with pytest.raises(ApunteNoEncontrado):
            borrar_apunte(db, USUARIO, malo.id)

    def test_corregir_el_importe(self, db):
        apunte = crear_apunte(db, USUARIO, "Cambio de grifo 1200", origen="bot")
        corregido = actualizar_apunte(db, USUARIO, apunte.id, importe=Decimal("120"))

        assert corregido.importe == Decimal("120")
        assert corregido.concepto == "Cambio de grifo", "no debe tocar lo que no se le pasa"

    def test_no_se_pueden_tocar_los_apuntes_de_otro(self, db):
        mio = crear_apunte(db, USUARIO, "Trabajo 100", origen="bot")

        with pytest.raises(ApunteNoEncontrado):
            borrar_apunte(db, OTRO, mio.id)
        with pytest.raises(ApunteNoEncontrado):
            marcar_cobrado(db, OTRO, mio.id)
        with pytest.raises(ApunteNoEncontrado):
            actualizar_apunte(db, OTRO, mio.id, importe=Decimal("1"))


class TestNotas:
    """Lo que no lleva importe, venga escrito o dictado, no se tira."""

    def test_lo_escrito_sin_importe_se_guarda_como_nota(self, db):
        resultado = anotar(
            db, USUARIO, "Llamar al fontanero el martes", origen="bot", admite_nota=True
        )

        assert resultado.apunte.tipo == "nota"
        assert resultado.apunte.importe == Decimal("0")

    def test_sin_admitir_notas_se_sigue_rechazando(self, db):
        """La API vieja y cualquier sitio que quiera un importe de verdad."""
        with pytest.raises(TextoNoInterpretable):
            anotar(db, USUARIO, "Llamar al fontanero el martes", origen="bot")

    def test_una_nota_en_blanco_no_es_nada(self, db):
        with pytest.raises(TextoNoInterpretable):
            anotar(db, USUARIO, "   ", origen="bot", admite_nota=True)

    def test_una_nota_no_suma_en_el_resumen(self, db):
        anotar(db, USUARIO, "Pasar a ver la caldera", origen="bot", admite_nota=True)
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")

        r = resumen_dia(db, USUARIO)
        assert r.cobrado == Decimal("120")
        assert r.neto == Decimal("120")


class TestClientes:
    def test_anotar_reconoce_al_cliente_y_lo_asigna(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        resultado = anotar(db, USUARIO, "Cambio de grifo ana 120", origen="bot")

        assert resultado.apunte.cliente_id == ana.id
        assert resultado.candidatos == []

    def test_con_dos_anas_no_asigna_y_devuelve_las_dos(self, db):
        crear_cliente(db, USUARIO, "Ana Ruiz")
        crear_cliente(db, USUARIO, "Ana Pérez")

        resultado = anotar(db, USUARIO, "Cambio de grifo ana 120", origen="bot")

        assert resultado.apunte.cliente_id is None, "mejor sin cliente que con el equivocado"
        assert len(resultado.candidatos) == 2

    def test_borrar_un_cliente_no_borra_su_dinero(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        crear_apunte(db, USUARIO, "pendiente Reforma 980", origen="web", cliente_id=ana.id)

        borrar_cliente(db, USUARIO, ana.id)

        pendientes = pendientes_de_cobro(db, USUARIO)
        assert len(pendientes) == 1, "el trabajo sigue ahí"
        assert pendientes[0].cliente_id is None, "solo queda suelto"

    def test_no_se_ve_la_ficha_de_un_cliente_ajeno(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        with pytest.raises(ClienteNoEncontrado):
            ficha_cliente(db, OTRO, ana.id)

    def test_los_pendientes_salen_del_mas_viejo_al_mas_nuevo(self, db):
        viejo = crear_apunte(db, USUARIO, "pendiente Antiguo 100", origen="web")
        actualizar_apunte(db, USUARIO, viejo.id, fecha=date.today() - timedelta(days=60))
        crear_apunte(db, USUARIO, "pendiente Reciente 200", origen="web")

        conceptos = [a.concepto for a in pendientes_de_cobro(db, USUARIO)]
        assert conceptos == ["Antiguo", "Reciente"]


class TestAgenda:
    def test_las_citas_con_hora_van_antes_que_las_de_sin_hora(self, db):
        hoy = date.today()
        crear_cita(db, USUARIO, hoy, "Pasar a cobrar")
        crear_cita(db, USUARIO, hoy, "Presupuesto", hora=time(9, 30))

        assert [c.titulo for c in citas_del_dia(db, USUARIO, hoy)] == [
            "Presupuesto",
            "Pasar a cobrar",
        ]

    def test_una_cita_hecha_sale_de_las_proximas(self, db):
        cita = crear_cita(db, USUARIO, date.today(), "Montar radiador", hora=time(8, 0))
        assert [c.id for c in proximas_citas(db, USUARIO)] == [cita.id]

        marcar_hecha(db, USUARIO, cita.id)
        assert proximas_citas(db, USUARIO) == []

    def test_no_se_toca_la_cita_de_otro(self, db):
        cita = crear_cita(db, USUARIO, date.today(), "Mía")
        with pytest.raises(CitaNoEncontrada):
            marcar_hecha(db, OTRO, cita.id)


class TestAvisos:
    def test_estan_activos_sin_haber_configurado_nada(self, db):
        assert avisos_activos(db, USUARIO) is True

    def test_no_se_avisa_a_quien_no_ha_anotado_nada(self, db):
        assert destinatarios_del_aviso(db) == []

    def test_se_avisa_a_quien_anoto_hoy(self, db):
        crear_apunte(db, USUARIO, "Trabajo 100", origen="bot")
        assert [a.user_id for a in destinatarios_del_aviso(db)] == [USUARIO]

    def test_se_avisa_a_quien_tiene_cita_manana_aunque_hoy_no_anotara(self, db):
        crear_cita(db, USUARIO, date.today() + timedelta(days=1), "Montar radiador")

        avisos = destinatarios_del_aviso(db)
        assert [a.user_id for a in avisos] == [USUARIO]
        assert avisos[0].hubo_apuntes is False
        assert len(avisos[0].citas_manana) == 1

    def test_quien_los_apaga_no_recibe_nada(self, db):
        crear_apunte(db, USUARIO, "Trabajo 100", origen="bot")
        activar_avisos(db, USUARIO, False)

        assert destinatarios_del_aviso(db) == []
