"""Convertir fotos de tickets en un PDF con aspecto de documento escaneado.

Es lo que hacía CamScanner: la foto pasa a blanco y negro con el contraste
estirado (el papel queda blanco y la tinta negra, sin la sombra amarillenta
de la luz de la cocina), se le quita la mesa de alrededor y va centrada en una página A4. Así se imprime, se
manda a la gestoría o se archiva como un documento, no como una foto.

No sabe qué es un gasto: recibe imágenes y devuelve bytes de PDF.
"""
import io
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

# A4 a 150 ppp: de sobra para leer un ticket y el PDF no pesa megas.
_A4 = (1240, 1754)
_MARGEN = 60


def _umbral_otsu(gris: Image.Image) -> int:
    """El gris que mejor separa lo claro (papel) de lo oscuro (mesa, sombra)."""
    histograma = gris.histogram()
    total = sum(histograma)
    suma_total = sum(i * n for i, n in enumerate(histograma))
    suma_fondo = peso_fondo = 0
    mejor, umbral = -1.0, 128
    for i, n in enumerate(histograma):
        peso_fondo += n
        if peso_fondo == 0:
            continue
        peso_frente = total - peso_fondo
        if peso_frente == 0:
            break
        suma_fondo += i * n
        media_fondo = suma_fondo / peso_fondo
        media_frente = (suma_total - suma_fondo) / peso_frente
        varianza = peso_fondo * peso_frente * (media_fondo - media_frente) ** 2
        if varianza > mejor:
            mejor, umbral = varianza, i
    return umbral


def _recortar_papel(gris: Image.Image) -> Image.Image:
    """Quita la mesa de alrededor quedándose con la zona clara más grande.

    Se trabaja sobre una copia pequeña y suavizada para que la letra del
    ticket no cuente como "oscuro" y parta el papel en trozos. Si lo claro
    ocupa casi todo o casi nada, la foto ya está encuadrada (o es rara) y se
    deja como está: recortar mal es peor que no recortar.
    """
    escala = 300 / max(gris.size)
    peque = gris.resize(
        (max(1, int(gris.width * escala)), max(1, int(gris.height * escala)))
    ).filter(ImageFilter.MedianFilter(9))
    umbral = _umbral_otsu(peque)
    caja = peque.point(lambda v: 255 if v > umbral else 0).getbbox()
    if not caja:
        return gris
    ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    proporcion = (ancho * alto) / (peque.width * peque.height)
    if not 0.15 < proporcion < 0.92:
        return gris
    # Un poco hacia dentro: mejor perder un milímetro de papel que dejar
    # un marco negro de mesa alrededor.
    margen = -2
    return gris.crop(
        (
            max(0, int((caja[0] - margen) / escala)),
            max(0, int((caja[1] - margen) / escala)),
            min(gris.width, int((caja[2] + margen) / escala)),
            min(gris.height, int((caja[3] + margen) / escala)),
        )
    )


def _percentil(gris: Image.Image, fraccion: float) -> int:
    histograma = gris.histogram()
    objetivo = sum(histograma) * fraccion
    acumulado = 0
    for valor, n in enumerate(histograma):
        acumulado += n
        if acumulado >= objetivo:
            return valor
    return 255


def _niveles_de_documento(gris: Image.Image) -> Image.Image:
    """El papel a blanco puro y la tinta a negro, como un escáner.

    En un ticket casi todo es papel, así que el tono del papel es el de la
    mayoría de los píxeles (percentil 50) y la tinta lo más oscuro que haya
    (percentil 0,5). Un autocontraste normal no sirve: como la letra es tan
    poca, la confunde con ruido y deja el papel en gris.
    """
    papel = _percentil(gris, 0.5)
    tinta = _percentil(gris, 0.005)
    # Un poco por debajo del papel: las arrugas y la sombra suave también
    # pasan a blanco en vez de quedarse como manchas.
    blanco = max(papel - 12, tinta + 1)
    if blanco - tinta < 20:  # foto plana (casi todo igual): no se toca
        return gris
    escala = 255 / (blanco - tinta)
    return gris.point(lambda v: 0 if v <= tinta else 255 if v >= blanco else int((v - tinta) * escala))


class ImagenNoLegible(ValueError):
    """La imagen no se puede abrir (formato raro o fichero dañado)."""


def _como_escaneado(ruta: Path) -> Image.Image:
    try:
        with Image.open(ruta) as original:
            # Las fotos del móvil guardan el giro aparte: sin esto salen tumbadas.
            foto = ImageOps.exif_transpose(original).convert("L")
    except (OSError, ValueError) as exc:
        raise ImagenNoLegible(f"no se puede abrir {ruta.name}") from exc
    foto = _recortar_papel(foto)
    foto = _niveles_de_documento(foto)

    pagina = Image.new("L", _A4, 255)
    hueco = (_A4[0] - 2 * _MARGEN, _A4[1] - 2 * _MARGEN)
    foto.thumbnail(hueco, Image.LANCZOS)
    pagina.paste(foto, ((_A4[0] - foto.width) // 2, _MARGEN))
    return pagina


def imagenes_a_pdf(rutas: list[Path]) -> bytes:
    """Un PDF con una página por imagen, en el orden dado."""
    if not rutas:
        raise ValueError("no hay imágenes que convertir")
    paginas = [_como_escaneado(r) for r in rutas]
    salida = io.BytesIO()
    paginas[0].save(
        salida, format="PDF", save_all=True, append_images=paginas[1:], resolution=150
    )
    return salida.getvalue()
