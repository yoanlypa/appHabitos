"""Poner la hoja recta y de frente, como si se hubiera pasado por un escáner.

Es la función estrella de CamScanner: en la foto el ticket sale torcido y en
trapecio (la cámara lo ve desde arriba y de lado). Aquí se buscan sus cuatro
esquinas y se "estira" la imagen para que esas esquinas pasen a ser las de un
rectángulo. Con OpenCV, que es lo que usan esas apps por dentro.

Cómo se encuentra la hoja: bordes (Canny) sobre una copia pequeña, el
contorno más grande, y si se puede simplificar a cuatro puntos, ésas son las
esquinas. Si el ticket está arrugado y no da cuatro puntos limpios, se usa el
rectángulo girado que mejor lo encierra: no corrige el trapecio pero sí lo
endereza.

Si no se encuentra nada que parezca una hoja, devuelve None y quien llama
sigue como antes: deformar la foto por una "hoja" que no es la de verdad es
mucho peor que dejarla como estaba.
"""
import cv2
import numpy as np
from PIL import Image

# Por debajo de esto no es la hoja sino una mancha, un logo o una sombra.
_AREA_MINIMA = 0.12
# Casi toda la foto: o ya está encuadrada o se ha detectado el borde de la
# propia imagen. En los dos casos no hay nada que enderezar.
_AREA_MAXIMA = 0.98
_LADO_TRABAJO = 700


def _ordenar(puntos: np.ndarray) -> np.ndarray:
    """Arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    puntos = puntos.reshape(4, 2).astype("float32")
    suma = puntos.sum(axis=1)
    resta = np.diff(puntos, axis=1).ravel()
    return np.array(
        [
            puntos[np.argmin(suma)],
            puntos[np.argmin(resta)],
            puntos[np.argmax(suma)],
            puntos[np.argmax(resta)],
        ],
        dtype="float32",
    )


def _esquinas(gris: np.ndarray) -> np.ndarray | None:
    """Las cuatro esquinas de la hoja en la imagen pequeña, o None."""
    area_total = gris.shape[0] * gris.shape[1]
    suave = cv2.GaussianBlur(gris, (5, 5), 0)

    # Dos formas de ver la hoja: por sus bordes (va bien con mesa de
    # textura) y por ser lo claro (va bien con mesa lisa y oscura).
    bordes = cv2.dilate(cv2.Canny(suave, 40, 140), np.ones((5, 5), np.uint8), iterations=2)
    _, claro = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    claro = cv2.morphologyEx(claro, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))

    candidatos = []
    for mascara in (bordes, claro):
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidatos.extend(contornos)
    candidatos.sort(key=cv2.contourArea, reverse=True)

    for contorno in candidatos[:6]:
        area = cv2.contourArea(contorno)
        if not _AREA_MINIMA * area_total < area < _AREA_MAXIMA * area_total:
            continue
        perimetro = cv2.arcLength(contorno, True)
        aproximado = cv2.approxPolyDP(contorno, 0.02 * perimetro, True)
        if len(aproximado) == 4 and cv2.isContourConvex(aproximado):
            return _ordenar(aproximado)

    # Sin cuatro esquinas limpias: el rectángulo girado del contorno mayor.
    for contorno in candidatos[:3]:
        area = cv2.contourArea(contorno)
        if _AREA_MINIMA * area_total < area < _AREA_MAXIMA * area_total:
            return _ordenar(cv2.boxPoints(cv2.minAreaRect(contorno)))
    return None


def enderezar(foto: Image.Image) -> Image.Image | None:
    """La hoja recta y recortada (en gris), o None si no se encuentra."""
    gris = np.array(foto.convert("L"))
    escala = _LADO_TRABAJO / max(gris.shape)
    if escala < 1:
        peque = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    else:
        peque, escala = gris, 1.0

    esquinas = _esquinas(peque)
    if esquinas is None:
        return None
    esquinas /= escala

    tl, tr, br, bl = esquinas
    ancho = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    alto = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    if ancho < 50 or alto < 50:
        return None
    destino = np.array(
        [[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]], dtype="float32"
    )
    matriz = cv2.getPerspectiveTransform(esquinas, destino)
    recta = cv2.warpPerspective(
        gris, matriz, (ancho, alto), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    # Los bordes se detectan algo hinchados (se dilatan para cerrar el
    # contorno), así que se recorta un poco hacia dentro: mejor perder un
    # milímetro de papel que dejar un marco negro de mesa.
    dentro_x, dentro_y = max(2, int(ancho * 0.02)), max(2, int(alto * 0.015))
    recta = recta[dentro_y : alto - dentro_y, dentro_x : ancho - dentro_x]
    ancho, alto = recta.shape[1], recta.shape[0]

    # Un ticket es más alto que ancho: si sale tumbado, se pone de pie.
    if ancho > alto * 1.15:
        recta = cv2.rotate(recta, cv2.ROTATE_90_CLOCKWISE)
    return Image.fromarray(recta)
