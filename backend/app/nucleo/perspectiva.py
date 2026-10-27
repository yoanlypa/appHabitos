"""Poner la hoja recta y de frente, como si se hubiera pasado por un escáner.

Es la función estrella de CamScanner: en la foto el ticket sale torcido y en
trapecio (la cámara lo ve desde arriba y de lado). Aquí se buscan sus cuatro
esquinas y se "estira" la imagen para que esas esquinas pasen a ser las de un
rectángulo. Con OpenCV, que es lo que usan esas apps por dentro.

Cómo se encuentra la hoja, en dos intentos: primero el borde del papel
contra la mesa (con la letra borrada antes, que si no cada línea de texto es
un borde más). Si no se ve, como con papel blanco sobre mesa blanca, el
contorno de lo impreso, que sigue la forma torcida de la hoja.

Si no se encuentra nada que parezca una hoja, devuelve None y quien llama
sigue como antes: deformar la foto por una "hoja" que no es la de verdad es
mucho peor que dejarla como estaba.
"""
import cv2
import numpy as np
from PIL import Image

# Por debajo de esto no es la hoja sino la tabla, un logo o una sombra.
_AREA_MINIMA = 0.25
# Casi toda la foto: se ha detectado el marco de la propia imagen, no la
# hoja (pasó con una factura real sobre una mesa blanca). No vale.
_AREA_MAXIMA = 0.90
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


def _cuadrilatero(contorno: np.ndarray) -> np.ndarray | None:
    """El contorno simplificado a cuatro puntos, si se deja."""
    perimetro = cv2.arcLength(contorno, True)
    for factor in np.linspace(0.015, 0.08, 14):
        aproximado = cv2.approxPolyDP(contorno, factor * perimetro, True)
        if len(aproximado) == 4 and cv2.isContourConvex(aproximado):
            return aproximado
        if len(aproximado) < 4:
            break
    return None


def _por_los_bordes(gris: np.ndarray) -> np.ndarray | None:
    """Primer intento: el borde del papel contra la mesa.

    Antes se "borra" la letra (cierre morfológico): si no, cada línea de
    texto es un borde más y el del papel se pierde entre ellos.
    """
    area_total = gris.shape[0] * gris.shape[1]
    sin_texto = cv2.morphologyEx(gris, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=3)
    suave = cv2.GaussianBlur(sin_texto, (7, 7), 0)
    bordes = cv2.dilate(cv2.Canny(suave, 20, 60), np.ones((5, 5), np.uint8), iterations=2)
    _, claro = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    candidatos = []
    for mascara in (bordes, claro):
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidatos.extend(contornos)
    candidatos.sort(key=cv2.contourArea, reverse=True)

    for contorno in candidatos[:6]:
        if not _AREA_MINIMA * area_total < cv2.contourArea(contorno) < _AREA_MAXIMA * area_total:
            continue
        cuatro = _cuadrilatero(contorno)
        if cuatro is not None:
            return _ordenar(cuatro)
    return None


def _puntos_impresos(gris: np.ndarray) -> np.ndarray | None:
    """Los píxeles de lo impreso (texto, tabla, logos), sin motas sueltas.

    La tinta se busca por ser más oscura que lo de alrededor (umbral
    adaptativo), así no la confunde el degradado de luz de la foto.
    """
    tinta = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15
    )
    tinta = cv2.morphologyEx(tinta, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    # Solo grupos grandes (líneas de texto, la tabla): una mota de polvo en
    # la mesa no puede estirar el contorno.
    agrupada = cv2.dilate(tinta, np.ones((5, 15), np.uint8))
    n, etiquetas, datos, _ = cv2.connectedComponentsWithStats(agrupada)
    grandes = np.isin(etiquetas, [i for i in range(1, n) if datos[i, cv2.CC_STAT_AREA] > 150])
    return cv2.findNonZero(grandes.astype(np.uint8))


def _por_el_contenido(gris: np.ndarray, puntos: np.ndarray | None) -> np.ndarray | None:
    """Segundo intento: el contorno de lo impreso (texto, tabla, logos).

    Para papel blanco sobre mesa blanca, donde el borde de la hoja casi no
    se ve pero lo impreso sí, y llega hasta cerca de los bordes: su contorno
    torcido es el de la hoja.
    """
    area_total = gris.shape[0] * gris.shape[1]
    if puntos is None:
        return None
    envolvente = cv2.convexHull(puntos)
    if not _AREA_MINIMA * area_total < cv2.contourArea(envolvente) < 0.97 * area_total:
        return None
    cuatro = _cuadrilatero(envolvente)
    if cuatro is None:
        return None
    esquinas = _ordenar(cuatro)
    # Un poco hacia fuera: lo impreso no llega al filo del papel, y cortar
    # un margen de la factura es peor que dejar un poco de mesa.
    centro = esquinas.mean(axis=0)
    esquinas = centro + (esquinas - centro) * 1.03
    alto, ancho = gris.shape
    esquinas[:, 0] = esquinas[:, 0].clip(0, ancho - 1)
    esquinas[:, 1] = esquinas[:, 1].clip(0, alto - 1)
    return esquinas


def _esquinas(gris: np.ndarray) -> np.ndarray | None:
    """Las cuatro esquinas de la hoja en la imagen pequeña, o None."""
    impresos = _puntos_impresos(gris)
    por_bordes = _por_los_bordes(gris)
    if por_bordes is not None and _contiene_lo_impreso(por_bordes, impresos):
        return por_bordes
    return _por_el_contenido(gris, impresos)


def _contiene_lo_impreso(esquinas: np.ndarray, puntos: np.ndarray | None) -> bool:
    """Un borde de "hoja" que deja fuera parte de la letra no es la hoja.

    Pasó con una factura real sobre una mesa blanca: un contorno de sombras
    salía con cuatro esquinas y la deformaba entera. La hoja de verdad tiene
    dentro todo lo impreso.
    """
    if puntos is None:
        return True
    muestra = puntos.reshape(-1, 2)[:: max(1, len(puntos) // 2000)].astype("float32")
    poligono = esquinas.reshape(-1, 1, 2)
    # Con margen: el propio filo del papel contra una mesa oscura sale como
    # "tinta" pegada por fuera (el umbral adaptativo mira 25 px alrededor).
    # Lo que cuenta es la letra que queda claramente fuera.
    fuera = sum(cv2.pointPolygonTest(poligono, (float(x), float(y)), True) < -15 for x, y in muestra)
    return fuera / len(muestra) < 0.02


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
