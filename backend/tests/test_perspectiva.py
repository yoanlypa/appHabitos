"""Enderezar la hoja: que una foto en trapecio salga recta, y que una foto sin
hoja no se deforme por una "hoja" inventada (eso sería peor que no tocarla).
"""
import cv2
import numpy as np
from PIL import Image

from app.nucleo.perspectiva import enderezar


def _ticket_torcido() -> Image.Image:
    ticket = np.full((1200, 500), 215, np.uint8)
    for y in range(80, 900, 60):
        cv2.line(ticket, (40, y), (360, y), 40, 4)  # "líneas de texto"
    mesa = np.full((1600, 1400), 80, np.uint8)
    origen = np.float32([[0, 0], [500, 0], [500, 1200], [0, 1200]])
    destino = np.float32([[380, 180], [900, 260], [1000, 1400], [300, 1330]])
    M = cv2.getPerspectiveTransform(origen, destino)
    torcido = cv2.warpPerspective(ticket, M, (1400, 1600))
    mascara = cv2.warpPerspective(np.full((1200, 500), 255, np.uint8), M, (1400, 1600))
    mesa[mascara > 0] = torcido[mascara > 0]
    return Image.fromarray(mesa)


def test_una_hoja_en_trapecio_sale_recta_y_sin_mesa():
    recta = enderezar(_ticket_torcido())
    assert recta is not None
    assert recta.height > recta.width  # de pie, como un ticket
    pixeles = np.array(recta)
    # Las líneas de texto quedan horizontales: cada fila es casi uniforme
    # fuera del texto, y los bordes son papel, no mesa.
    for borde in (pixeles[:, :5], pixeles[:, -5:], pixeles[:5, :], pixeles[-5:, :]):
        assert borde.mean() > 170


def test_sin_hoja_no_se_inventa_nada():
    liso = Image.new("L", (800, 1000), 128)
    assert enderezar(liso) is None


def test_una_foto_ya_encuadrada_no_se_toca():
    papel = Image.new("L", (800, 1000), 230)
    assert enderezar(papel) is None


def test_papel_blanco_sobre_mesa_blanca_se_endereza_por_lo_impreso():
    """El caso de una factura real: el filo del papel casi no se ve, la letra sí.

    Hoja de 235 sobre mesa de 225, girada 6 grados: el borde no basta y hay
    que guiarse por el contenido. Antes salía la foto tal cual, torcida.
    """
    hoja = np.full((1100, 800), 235, np.uint8)
    for y in range(60, 1040, 45):
        cv2.line(hoja, (50, y), (750, y), 30, 6)  # renglones de borde a borde
    mesa = np.full((1500, 1200), 225, np.uint8)
    giro = cv2.getRotationMatrix2D((400, 550), 6, 1.0)
    giro[:, 2] += (200, 200)
    girada = cv2.warpAffine(hoja, giro, (1200, 1500), borderValue=225)
    mesa[:] = girada
    recta = enderezar(Image.fromarray(mesa))
    assert recta is not None
    # Los renglones quedan horizontales: cada uno es una franja oscura
    # seguida, no una diagonal que cruza varias filas.
    pixeles = np.array(recta)
    filas_oscuras = (pixeles < 120).mean(axis=1)
    assert filas_oscuras.max() > 0.8


def _dos_papeles():
    """Un ticket estrecho y, al lado, otro papel con letra (como en la foto real
    de la gasolinera). El borde del ticket no tiene dentro TODA la letra."""
    mesa = np.full((1400, 1100), 40, np.uint8)
    cv2.rectangle(mesa, (420, 60), (700, 1340), 235, -1)  # el ticket
    for y in range(100, 1300, 40):
        cv2.line(mesa, (450, y), (670, y), 30, 5)
    # Otro papel con menos letra (en la foto real tenía el 16 % del total).
    cv2.rectangle(mesa, (20, 20), (300, 300), 230, -1)
    for y in range(60, 260, 40):
        cv2.line(mesa, (40, y), (280, y), 30, 5)
    return Image.fromarray(mesa)


def test_con_otro_papel_al_lado_se_queda_con_el_ticket():
    """Sin ayuda de la IA, el filo vale si tiene dentro casi toda la letra."""
    recta = enderezar(_dos_papeles())
    assert recta is not None
    # El ticket es alto y estrecho (280 × 1280): si se hubiera metido el otro
    # papel, saldría mucho más ancho.
    assert recta.height / recta.width > 3


def test_las_esquinas_de_la_ia_mandan_si_son_creibles():
    sugeridas = [[0.38, 0.04], [0.64, 0.04], [0.64, 0.96], [0.38, 0.96]]
    recta = enderezar(_dos_papeles(), sugeridas)
    assert recta is not None and recta.height / recta.width > 3


def test_unas_esquinas_absurdas_de_la_ia_se_ignoran():
    absurdas = [[0.9, 0.9], [0.95, 0.9], [0.95, 0.95], [0.9, 0.95]]  # una mota
    recta = enderezar(_dos_papeles(), absurdas)
    assert recta is not None and recta.height / recta.width > 3
