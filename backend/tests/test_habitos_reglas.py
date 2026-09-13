"""Las reglas de los hábitos, con fechas inventadas.

Lo que se prueba es lo que decide si la app anima o desanima: que descansar
el sábado no rompa la racha de entrenar de lunes a viernes, que la racha no
amanezca rota cada mañana, y que el primer día no salga con un 0%.
"""
from datetime import date, timedelta

import pytest

from app.dominio.habitos import (
    ANTES,
    FALLADO,
    FUTURO,
    HECHO,
    HOY,
    NO_TOCA,
    TODOS_LOS_DIAS,
    DiasNoValidos,
    cumplimiento,
    dias_a_texto,
    dias_del_mes,
    dias_desde_texto,
    estado_del_dia,
    mejor_racha,
    racha_actual,
    semana,
)

LUNES = date(2026, 9, 7)
LABORABLES = frozenset(range(5))


def seguidos(desde: date, cuantos: int) -> set[date]:
    return {desde + timedelta(days=i) for i in range(cuantos)}


class TestDias:
    def test_ida_y_vuelta(self):
        assert dias_desde_texto(dias_a_texto([4, 0, 2])) == frozenset({0, 2, 4})
        assert dias_a_texto(TODOS_LOS_DIAS) == "0123456"

    def test_un_habito_que_no_toca_nunca_no_es_un_habito(self):
        with pytest.raises(DiasNoValidos):
            dias_a_texto([])

    def test_no_hay_octavo_dia(self):
        with pytest.raises(DiasNoValidos):
            dias_a_texto([7])


class TestRachaActual:
    def test_hoy_sin_marcar_no_rompe_la_racha(self):
        """Si rompiera, la racha amanecería rota cada mañana."""
        hoy = LUNES + timedelta(days=5)
        hechos = seguidos(LUNES, 5)  # de lunes a viernes; hoy es sábado sin marcar

        assert racha_actual(TODOS_LOS_DIAS, hechos, LUNES, hoy) == 5

    def test_hoy_marcado_suma(self):
        hoy = LUNES + timedelta(days=5)
        assert racha_actual(TODOS_LOS_DIAS, seguidos(LUNES, 6), LUNES, hoy) == 6

    def test_un_dia_fallado_si_la_rompe(self):
        hoy = LUNES + timedelta(days=5)
        hechos = seguidos(LUNES, 3)  # falló el jueves y el viernes

        assert racha_actual(TODOS_LOS_DIAS, hechos, LUNES, hoy) == 0

    def test_el_fin_de_semana_de_un_habito_de_laborables_no_la_rompe(self):
        siguiente_lunes = LUNES + timedelta(days=7)
        hechos = seguidos(LUNES, 5)  # toda la semana laboral, y hoy lunes sin marcar

        assert racha_actual(LABORABLES, hechos, LUNES, siguiente_lunes) == 5

    def test_un_habito_recien_creado_empieza_en_cero(self):
        assert racha_actual(TODOS_LOS_DIAS, set(), LUNES, LUNES) == 0


class TestMejorRacha:
    def test_se_queda_con_la_mas_larga(self):
        hoy = LUNES + timedelta(days=20)
        hechos = seguidos(LUNES, 3) | seguidos(LUNES + timedelta(days=4), 5)

        assert mejor_racha(TODOS_LOS_DIAS, hechos, LUNES, hoy) == 5

    def test_la_racha_en_curso_cuenta_aunque_hoy_falte(self):
        hoy = LUNES + timedelta(days=4)
        assert mejor_racha(TODOS_LOS_DIAS, seguidos(LUNES, 4), LUNES, hoy) == 4


class TestCumplimiento:
    def test_el_primer_dia_no_sale_con_un_cero_por_ciento(self):
        """Hoy sin hacer no cuenta todavía: (0, 0), no (0, 1)."""
        assert cumplimiento(TODOS_LOS_DIAS, set(), LUNES, LUNES) == (0, 0)

    def test_cuenta_solo_los_dias_que_tocaban(self):
        domingo = LUNES + timedelta(days=6)
        hechos = {LUNES, LUNES + timedelta(days=2)}

        # De lunes a domingo tocaban 5 (laborables) y se hicieron 2.
        assert cumplimiento(LABORABLES, hechos, LUNES, domingo) == (2, 5)


class TestEstados:
    def test_cada_dia_con_su_estado(self):
        martes, miercoles = LUNES + timedelta(days=1), LUNES + timedelta(days=2)
        hoy = miercoles
        hechos = {LUNES}
        inicio = LUNES

        assert estado_del_dia(LABORABLES, hechos, inicio, hoy, LUNES) == HECHO
        assert estado_del_dia(LABORABLES, hechos, inicio, hoy, martes) == FALLADO
        assert estado_del_dia(LABORABLES, hechos, inicio, hoy, miercoles) == HOY
        assert estado_del_dia(LABORABLES, hechos, inicio, hoy, LUNES + timedelta(days=3)) == FUTURO
        assert estado_del_dia(LABORABLES, hechos, inicio, hoy, LUNES + timedelta(days=5)) == NO_TOCA

    def test_antes_de_empezar_no_es_un_fallo(self):
        """No se puede fallar algo que todavía no existía."""
        viernes_anterior = LUNES - timedelta(days=3)
        assert estado_del_dia(LABORABLES, set(), LUNES, LUNES, viernes_anterior) == ANTES

    def test_la_semana_va_de_lunes_a_domingo(self):
        jueves = LUNES + timedelta(days=3)
        dias = semana(TODOS_LOS_DIAS, set(), LUNES, jueves)

        assert [d.fecha for d in dias] == [LUNES + timedelta(days=i) for i in range(7)]
        assert dias[3].estado == HOY

    def test_el_mes_tiene_todos_sus_dias(self):
        assert len(dias_del_mes(TODOS_LOS_DIAS, set(), LUNES, LUNES, 2026, 2)) == 28
        assert len(dias_del_mes(TODOS_LOS_DIAS, set(), LUNES, LUNES, 2026, 9)) == 30
