"""Las reglas puras: interpretar texto, fechas y nombres de clientes.

No tocan base de datos, así que son los tests más rápidos y los que más
casos límite cubren.
"""
from datetime import date, time
from decimal import Decimal

import pytest

from app.dominio.deteccion_clientes import Candidato, buscar_clientes
from app.dominio.parsing import TextoNoInterpretable, interpretar_texto
from app.dominio.parsing_citas import CitaNoInterpretable, interpretar_cita

VIERNES = date(2026, 9, 4)


class TestApuntes:
    def test_trabajo_cobrado(self):
        r = interpretar_texto("Cambio de grifo Ana 120")
        assert (r.tipo, r.concepto, r.importe, r.pendiente) == (
            "trabajo",
            "Cambio de grifo Ana",
            Decimal("120"),
            False,
        )

    def test_trabajo_pendiente(self):
        r = interpretar_texto("pendiente Reforma baño 980")
        assert r.pendiente is True
        assert r.concepto == "Reforma baño"

    def test_gasto(self):
        r = interpretar_texto("-45 gasolina")
        assert (r.tipo, r.concepto, r.importe) == ("gasto", "gasolina", Decimal("45"))

    def test_decimales_con_coma(self):
        assert interpretar_texto("Trabajo 45,50").importe == Decimal("45.50")

    def test_sin_importe_no_se_inventa_nada(self):
        with pytest.raises(TextoNoInterpretable):
            interpretar_texto("hola qué tal")

    def test_texto_vacio(self):
        with pytest.raises(TextoNoInterpretable):
            interpretar_texto("   ")


class TestDictado:
    """Lo que llega transcrito de una nota de voz.

    Nadie dice "menos cuarenta y cinco" ni se calla la palabra "euros", así
    que sin estas reglas media nota dictada acabaría sin importe.
    """

    def test_se_dice_euros_y_se_acaba_en_punto(self):
        r = interpretar_texto("Cambio de grifo Ana 120 euros.")
        assert (r.tipo, r.concepto, r.importe) == ("trabajo", "Cambio de grifo Ana", Decimal("120"))

    def test_el_simbolo_del_euro_tambien(self):
        assert interpretar_texto("Reforma baño 980 €").importe == Decimal("980")

    def test_pendiente_dictado(self):
        r = interpretar_texto("Pendiente reforma del baño 980 euros")
        assert r.pendiente is True
        assert r.concepto == "reforma del baño"

    def test_gasto_dicho_con_palabras(self):
        r = interpretar_texto("gasto de 45 en gasolina")
        assert (r.tipo, r.concepto, r.importe) == ("gasto", "gasolina", Decimal("45"))

    def test_gasto_con_el_importe_detras(self):
        r = interpretar_texto("gasto gasolina 45,50")
        assert (r.tipo, r.concepto, r.importe) == ("gasto", "gasolina", Decimal("45.50"))

    def test_los_euros_de_en_medio_no_son_el_concepto(self):
        assert interpretar_texto("gasto de 12 euros en tornillos").concepto == "tornillos"

    def test_un_gasto_sin_concepto_sigue_siendo_un_gasto(self):
        """Caer en la regla de trabajo lo apuntaría como dinero que entra."""
        r = interpretar_texto("gasto de 45 euros")
        assert (r.tipo, r.importe) == ("gasto", Decimal("45"))

    def test_menos_no_convierte_un_trabajo_en_gasto(self):
        """'menos mal que vino Ana' empieza por menos y no es ningún gasto."""
        assert interpretar_texto("menos mal que vino Ana 120").tipo == "trabajo"

    def test_lo_que_no_lleva_importe_se_sigue_rechazando(self):
        """Aquí no se decide guardar una nota: eso lo hace el servicio."""
        with pytest.raises(TextoNoInterpretable):
            interpretar_texto("Llamar al fontanero el martes")


class TestCitas:
    def test_manana_con_y_sin_tilde(self):
        con = interpretar_cita("mañana 10:00 Cambiar grifo", VIERNES)
        sin = interpretar_cita("manana 10:00 Cambiar grifo", VIERNES)
        assert con.fecha == sin.fecha == date(2026, 9, 5)
        assert con.hora == time(10, 0)

    def test_dia_de_la_semana_salta_al_siguiente(self):
        """Decir 'viernes' en viernes es el viernes que viene, no hoy."""
        assert interpretar_cita("viernes Revisar caldera", VIERNES).fecha == date(2026, 9, 11)

    def test_fecha_ya_pasada_se_entiende_del_ano_que_viene(self):
        assert interpretar_cita("01/01 Cena", VIERNES).fecha == date(2027, 1, 1)

    def test_un_numero_suelto_no_es_una_hora(self):
        """'Reforma 3 baños' no es una cita a las tres."""
        r = interpretar_cita("Reforma 3 baños", VIERNES)
        assert r.hora is None
        assert r.titulo == "Reforma 3 baños"

    def test_sin_titulo_no_hay_cita(self):
        with pytest.raises(CitaNoInterpretable):
            interpretar_cita("mañana 10:00", VIERNES)


class TestDeteccionDeClientes:
    GENTE = [
        Candidato(1, "Ana Ruiz"),
        Candidato(2, "Ana Pérez"),
        Candidato(3, "María José Gómez"),
        Candidato(4, "Luis"),
    ]

    def test_nombre_unico_se_reconoce(self):
        encontrados = buscar_clientes("Pintar valla Luis 200", self.GENTE)
        assert [c.id for c in encontrados] == [4]

    def test_dos_anas_devuelve_las_dos_para_preguntar(self):
        encontrados = buscar_clientes("Cambio de grifo ana 120", self.GENTE)
        assert {c.id for c in encontrados} == {1, 2}

    def test_el_apellido_desempata(self):
        """Decir 'Ana Ruiz' no debe preguntar por Ana Pérez."""
        encontrados = buscar_clientes("Reforma de Ana Ruiz 500", self.GENTE)
        assert [c.id for c in encontrados] == [1]

    def test_una_palabra_cualquiera_no_es_un_cliente(self):
        assert buscar_clientes("Cambio de grifo cocina 120", self.GENTE) == []

    def test_las_tildes_dan_igual(self):
        assert [c.id for c in buscar_clientes("reforma maria 300", self.GENTE)] == [3]
        assert [c.id for c in buscar_clientes("grifo Ana Ruíz 100", self.GENTE)] == [1]
