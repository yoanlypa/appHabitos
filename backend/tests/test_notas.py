"""El buzón de notas y las citas de varios días.

Lo que se prueba es el paso de una cosa a la otra, que es donde está el
riesgo: al agendar una nota tiene que nacer la cita **y** desaparecer la
nota, y una cita de tres días tiene que salir los tres, no solo el primero.
"""
from datetime import date, time, timedelta

import pytest

from app.servicios import notas as buzon
from app.servicios.agenda import (
    RangoAlReves,
    actualizar_cita,
    citas_del_dia,
    citas_del_mes,
    crear_cita,
    proximas_citas,
)
from app.servicios.apuntes import ApunteNoEncontrado, actualizar_apunte, crear_apunte, listar_apuntes
from app.servicios.clientes import crear_cliente
from app.servicios.export import exportar_csv, exportar_todo
from tests.conftest import USUARIO

OTRO = 111222333
HOY = date.today()


class TestBuzon:
    def test_la_nota_de_la_semana_pasada_sigue_en_el_buzon(self, db):
        """Una nota no caduca: el buzón no filtra por día como sí hace 'Hoy'."""
        vieja = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        actualizar_apunte(db, USUARIO, vieja.id, fecha=HOY - timedelta(days=8))

        assert [n.id for n in buzon.listar_notas(db, USUARIO)] == [vieja.id]

    def test_en_el_buzon_un_numero_al_final_no_es_dinero(self, db):
        """"Cambiar 2 grifos" es una tarea, no dos euros."""
        nota = buzon.crear(db, USUARIO, "Cambiar 2 grifos", origen="web")

        assert nota.tipo == "nota"
        assert nota.concepto == "Cambiar 2 grifos"

    def test_la_nota_se_cuelga_del_cliente_que_nombra(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        assert buzon.crear(db, USUARIO, "Presupuesto de Ana Ruiz", origen="web").cliente_id == ana.id

    def test_editar_y_borrar(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="web")

        assert buzon.editar(db, USUARIO, nota.id, "Revisar el coche y las ruedas").concepto == (
            "Revisar el coche y las ruedas"
        )
        buzon.borrar(db, USUARIO, nota.id)
        assert buzon.listar_notas(db, USUARIO) == []

    def test_no_se_toca_el_buzon_de_otro(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="web")
        with pytest.raises(ApunteNoEncontrado):
            buzon.borrar(db, OTRO, nota.id)
        with pytest.raises(ApunteNoEncontrado):
            buzon.editar(db, OTRO, nota.id, "mío ahora")

    def test_un_trabajo_no_se_edita_por_la_puerta_del_buzon(self, db):
        """El buzón solo toca notas: un apunte con dinero no es cosa suya."""
        trabajo = crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="web")
        with pytest.raises(ApunteNoEncontrado):
            buzon.editar(db, USUARIO, trabajo.id, "Cambio de grifo 1200")

    def test_las_notas_no_salen_en_la_lista_del_dia(self, db):
        """Esa lista es la del dinero; las notas tienen su propio sitio."""
        buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")

        assert [a.concepto for a in listar_apuntes(db, USUARIO)] == ["Cambio de grifo"]
        assert len(listar_apuntes(db, USUARIO, incluir_notas=True)) == 2

    def test_el_csv_del_gestor_no_lleva_notas_pero_la_copia_si(self, db):
        buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")

        assert "Revisar el coche" not in exportar_csv(db, USUARIO, HOY, HOY)
        assert "Revisar el coche" in exportar_todo(db, USUARIO)


class TestMarcarHecha:
    def test_lo_hecho_sale_del_buzon_pero_no_se_borra(self, db):
        """Cumplido y equivocado son cosas distintas: una se marca, otra se borra."""
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")

        buzon.marcar_hecha(db, USUARIO, nota.id)

        assert buzon.listar_notas(db, USUARIO) == []
        assert [n.id for n in buzon.listar_notas(db, USUARIO, hechas=True)] == [nota.id]
        assert len(buzon.listar_notas(db, USUARIO, hechas=None)) == 1

    def test_se_puede_devolver_al_buzon(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        buzon.marcar_hecha(db, USUARIO, nota.id)

        buzon.marcar_hecha(db, USUARIO, nota.id, hecha=False)

        assert [n.id for n in buzon.listar_notas(db, USUARIO)] == [nota.id]

    def test_una_nota_nace_por_hacer(self, db):
        assert buzon.crear(db, USUARIO, "Revisar el coche", origen="web").hecha is False

    def test_lo_hecho_ya_no_se_cuenta_en_el_aviso(self, db):
        """Si siguiera contando, el aviso diría 'tienes 8 notas' para siempre."""
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        assert buzon.contar_notas(db, USUARIO) == 1

        buzon.marcar_hecha(db, USUARIO, nota.id)
        assert buzon.contar_notas(db, USUARIO) == 0

    def test_no_se_marca_lo_de_otro(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="web")
        with pytest.raises(ApunteNoEncontrado):
            buzon.marcar_hecha(db, OTRO, nota.id)


class TestAgendarUnaNota:
    def test_al_ponerle_fecha_nace_la_cita_y_muere_la_nota(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")

        cita = buzon.agendar(db, USUARIO, nota.id, HOY)

        assert cita.titulo == "Revisar el coche"
        assert cita.fecha == HOY
        assert buzon.listar_notas(db, USUARIO) == [], "sale del buzón"
        assert [c.id for c in citas_del_dia(db, USUARIO, HOY)] == [cita.id]

    def test_se_puede_retocar_el_texto_al_agendarla(self, db):
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")

        cita = buzon.agendar(db, USUARIO, nota.id, HOY, titulo="Llevar el coche al taller")

        assert cita.titulo == "Llevar el coche al taller"

    def test_la_cita_hereda_el_cliente_de_la_nota(self, db):
        ana = crear_cliente(db, USUARIO, "Ana Ruiz")
        nota = buzon.crear(db, USUARIO, "Presupuesto de Ana Ruiz", origen="web")

        assert buzon.agendar(db, USUARIO, nota.id, HOY).cliente_id == ana.id

    def test_con_rango_de_dias_y_hora(self, db):
        nota = buzon.crear(db, USUARIO, "Reforma del baño", origen="web")

        cita = buzon.agendar(
            db, USUARIO, nota.id, HOY, fecha_fin=HOY + timedelta(days=2), hora=time(9, 0)
        )

        assert (cita.fecha, cita.fecha_fin, cita.hora) == (HOY, HOY + timedelta(days=2), time(9, 0))

    def test_un_rango_al_reves_no_agenda_ni_borra_la_nota(self, db):
        nota = buzon.crear(db, USUARIO, "Reforma del baño", origen="web")

        with pytest.raises(RangoAlReves):
            buzon.agendar(db, USUARIO, nota.id, HOY, fecha_fin=HOY - timedelta(days=1))

        assert len(buzon.listar_notas(db, USUARIO)) == 1, "lo apuntado no se pierde"

    def test_un_solo_dia_no_guarda_fecha_fin(self, db):
        """Repetir la fecha sería otra forma de escribir lo mismo."""
        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="web")
        assert buzon.agendar(db, USUARIO, nota.id, HOY, fecha_fin=HOY).fecha_fin is None


class TestCitasDeVariosDias:
    def test_sale_todos_los_dias_del_rango(self, db):
        """Si solo saliera el primer día, el miércoles parecería libre."""
        cita = crear_cita(
            db, USUARIO, HOY, "Reforma del baño", fecha_fin=HOY + timedelta(days=2)
        )

        for dias in (0, 1, 2):
            del_dia = citas_del_dia(db, USUARIO, HOY + timedelta(days=dias))
            assert [c.id for c in del_dia] == [cita.id], f"día {dias} del rango"
        assert citas_del_dia(db, USUARIO, HOY + timedelta(days=3)) == []

    def test_una_que_empezo_el_mes_pasado_sale_en_este(self, db):
        """El calendario de septiembre tiene que enseñar la reforma de agosto."""
        fin_de_mes = date(2026, 8, 30)
        crear_cita(db, USUARIO, fin_de_mes, "Reforma larga", fecha_fin=date(2026, 9, 2))

        assert len(citas_del_mes(db, USUARIO, 2026, 9)) == 1

    def test_una_en_curso_sigue_siendo_de_lo_que_viene(self, db):
        crear_cita(db, USUARIO, HOY - timedelta(days=1), "Reforma", fecha_fin=HOY)
        assert len(proximas_citas(db, USUARIO)) == 1

    def test_una_ya_terminada_no(self, db):
        crear_cita(
            db, USUARIO, HOY - timedelta(days=3), "Reforma", fecha_fin=HOY - timedelta(days=1)
        )
        assert proximas_citas(db, USUARIO) == []


class TestEditarUnaCita:
    def test_cambiar_el_texto_y_el_rango(self, db):
        cita = crear_cita(db, USUARIO, HOY, "Reforma")

        cambiada = actualizar_cita(
            db, USUARIO, cita.id, titulo="Reforma del baño", fecha_fin=HOY + timedelta(days=1)
        )

        assert cambiada.titulo == "Reforma del baño"
        assert cambiada.fecha_fin == HOY + timedelta(days=1)

    def test_quitar_la_hora_sin_tocar_lo_demas(self, db):
        """None significa 'quítala'; no mandar el campo significa 'no la toques'."""
        cita = crear_cita(db, USUARIO, HOY, "Reforma", hora=time(9, 0), direccion="Calle Mayor")

        sin_hora = actualizar_cita(db, USUARIO, cita.id, hora=None)

        assert sin_hora.hora is None
        assert sin_hora.direccion == "Calle Mayor"

    def test_mover_el_inicio_por_delante_del_fin_no_cuela(self, db):
        cita = crear_cita(db, USUARIO, HOY, "Reforma", fecha_fin=HOY + timedelta(days=1))

        with pytest.raises(RangoAlReves):
            actualizar_cita(db, USUARIO, cita.id, fecha=HOY + timedelta(days=5))


class TestElBotYElAviso:
    def test_el_buzon_por_telegram_lista_con_su_numero(self, db):
        """El número es lo que hace falta para poder /borrar la nota."""
        from app.bot import formato

        nota = buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        texto = formato.lista_notas(buzon.listar_notas(db, USUARIO))

        assert f"#{nota.id}" in texto
        assert "Revisar el coche" in texto

    def test_sin_notas_lo_dice_y_no_lista_nada(self, db):
        from app.bot import formato

        assert formato.lista_notas([]) == "No tienes notas pendientes."

    def test_una_nota_sola_no_hace_sonar_el_aviso_de_la_noche(self, db):
        """Si lo hiciera, una nota vieja avisaría todas las noches para siempre."""
        from app.servicios.avisos import destinatarios_del_aviso

        buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")

        assert destinatarios_del_aviso(db) == []

    def test_pero_a_quien_ya_recibe_el_aviso_se_le_cuentan(self, db):
        from app.servicios.avisos import destinatarios_del_aviso

        buzon.crear(db, USUARIO, "Revisar el coche", origen="bot")
        crear_apunte(db, USUARIO, "Cambio de grifo 120", origen="bot")

        avisos = destinatarios_del_aviso(db)
        assert [a.notas_pendientes for a in avisos] == [1]
