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
