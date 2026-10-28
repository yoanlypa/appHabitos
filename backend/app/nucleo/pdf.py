"""Convertir fotos de tickets en un PDF con aspecto de documento escaneado.

Es lo que hace CamScanner: la hoja se endereza de frente (`perspectiva.py`),
se le quita la mesa de alrededor, se borran las sombras y el tono amarillento
de la luz conservando el color de lo impreso, y va centrada en un A4. Así se
imprime, se manda a la gestoría o se archiva como un documento, no como una
foto.

No sabe qué es un gasto: recibe imágenes y devuelve bytes de PDF.
"""
import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.nucleo.perspectiva import enderezar

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


def _caja_papel(gris: Image.Image) -> tuple[int, int, int, int] | None:
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
        return None
    ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    proporcion = (ancho * alto) / (peque.width * peque.height)
    if not 0.15 < proporcion < 0.92:
        return None
    # Un poco hacia dentro: mejor perder un milímetro de papel que dejar
    # un marco negro de mesa alrededor.
    margen = -2
    return (
        max(0, int((caja[0] - margen) / escala)),
        max(0, int((caja[1] - margen) / escala)),
        min(gris.width, int((caja[2] + margen) / escala)),
        min(gris.height, int((caja[3] + margen) / escala)),
    )


class ImagenNoLegible(ValueError):
    """La imagen no se puede abrir (formato raro o fichero dañado)."""


def _como_escaneado(ruta: Path, esquinas: list | None = None) -> Image.Image:
    try:
        with Image.open(ruta) as original:
            # Las fotos del móvil guardan el giro aparte: sin esto salen tumbadas.
            foto = ImageOps.exif_transpose(original).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ImagenNoLegible(f"no se puede abrir {ruta.name}") from exc
    # Primero se endereza la hoja (esquinas → rectángulo, como un escáner).
    # Si no se encuentra, al menos se le quita la mesa.
    recta = enderezar(foto, esquinas)
    if recta is None:
        caja = _caja_papel(foto.convert("L"))
        recta = foto if caja is None else foto.crop(caja)
    hoja = _filtro_documento(recta)

    pagina = Image.new("RGB", _A4, "white")
    hueco = (_A4[0] - 2 * _MARGEN, _A4[1] - 2 * _MARGEN)
    hoja.thumbnail(hueco, Image.LANCZOS)
    pagina.paste(hoja, ((_A4[0] - hoja.width) // 2, _MARGEN))
    return pagina


def _filtro_documento(foto: Image.Image) -> Image.Image:
    """El filtro "mágico" de las apps de escaneo: papel blanco, color intacto.

    En vez de pasar a blanco y negro (que dejaba la letra fina rota y los
    logos en manchas), se estima la luz de fondo de cada zona y se divide por
    ella: las sombras y el tono amarillento desaparecen y lo impreso conserva
    su color. Después, un poco de contraste para que la tinta quede negra.
    """
    rgb = np.asarray(foto.convert("RGB"))
    canales = []
    for canal in cv2.split(rgb):
        # Fondo: cerrar quita la letra, la mediana suaviza lo que quede.
        fondo = cv2.medianBlur(cv2.dilate(canal, np.ones((15, 15), np.uint8)), 31)
        canales.append(cv2.divide(canal, fondo, scale=255))
    limpio = cv2.convertScaleAbs(cv2.merge(canales), alpha=1.25, beta=-60)
    return Image.fromarray(limpio)


@dataclass
class PaginaDeDatos:
    """Una página de texto: título, pares etiqueta-valor y una tabla.

    `nucleo/` no sabe qué es un ticket: quien llama decide qué filas van.
    """

    titulo: str
    filas: list[tuple[str, str]]
    cabecera: list[str] | None = None
    tabla: list[list[str]] | None = None
    pie: list[tuple[str, str]] | None = None


_FUENTES = Path(__file__).parent / "fuentes"


def _fuente(tamano: int, negrita: bool = False):
    """DejaVu Sans, que va dentro del proyecto (ver `fuentes/LEEME.txt`).

    La de Pillow no tiene tildes ni €: "Dirección" salía con cuadraditos.
    """
    nombre = "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(_FUENTES / nombre), tamano)
    except OSError:
        return ImageFont.load_default(size=tamano)


def _pagina_de_datos(datos: PaginaDeDatos) -> Image.Image:
    pagina = Image.new("RGB", _A4, "white")
    dibujo = ImageDraw.Draw(pagina)
    x, y = _MARGEN + 20, _MARGEN + 20
    ancho_util = _A4[0] - 2 * x
    texto, gris, linea = (20, 20, 20), (110, 110, 110), (210, 210, 210)

    dibujo.text((x, y), datos.titulo, font=_fuente(44, negrita=True), fill=texto)
    y += 80
    for etiqueta, valor in datos.filas:
        dibujo.text((x, y), etiqueta, font=_fuente(24), fill=gris)
        dibujo.text((x + 300, y), _cortar(dibujo, valor, _fuente(26), ancho_util - 300), font=_fuente(26), fill=texto)
        y += 42

    if datos.cabecera and datos.tabla:
        y += 30
        anchos = [0.55, 0.12, 0.16, 0.17]
        columnas = [x + int(ancho_util * sum(anchos[:i])) for i in range(len(anchos))]
        dibujo.line((x, y + 36, x + ancho_util, y + 36), fill=texto, width=2)
        for i, nombre in enumerate(datos.cabecera):
            dibujo.text((columnas[i] + (0 if i == 0 else 4), y), nombre, font=_fuente(22), fill=gris)
        y += 50
        for fila in datos.tabla:
            if y > _A4[1] - 320:  # sin sitio: se dice en vez de pisar el pie
                dibujo.text((x, y), "… (más líneas)", font=_fuente(22), fill=gris)
                y += 40
                break
            for i, celda in enumerate(fila):
                limite = int(ancho_util * anchos[i]) - 10
                dibujo.text((columnas[i] + (0 if i == 0 else 4), y), _cortar(dibujo, celda, _fuente(24), limite), font=_fuente(24), fill=texto)
            y += 40
            dibujo.line((x, y - 6, x + ancho_util, y - 6), fill=linea, width=1)

    if datos.pie:
        y += 30
        for etiqueta, valor in datos.pie:
            ultimo = etiqueta == datos.pie[-1][0]
            fuente = _fuente(34 if ultimo else 26, negrita=ultimo)
            ancho_valor = dibujo.textlength(valor, font=fuente)
            dibujo.text((x + ancho_util - 420, y), etiqueta, font=fuente, fill=texto if ultimo else gris)
            dibujo.text((x + ancho_util - ancho_valor, y), valor, font=fuente, fill=texto)
            y += 54 if ultimo else 42
    return pagina


def _cortar(dibujo, texto: str, fuente, ancho: int) -> str:
    """El texto recortado con "…" para que no se salga de su columna."""
    if dibujo.textlength(texto, font=fuente) <= ancho:
        return texto
    while texto and dibujo.textlength(texto + "…", font=fuente) > ancho:
        texto = texto[:-1]
    return texto + "…"


def imagenes_a_pdf(
    rutas: list[Path],
    esquinas: list | None = None,
    datos: list[PaginaDeDatos | None] | None = None,
) -> bytes:
    """Un PDF con una página por imagen, en el orden dado.

    `esquinas` y `datos` van en el mismo orden que `rutas`: las esquinas de
    la hoja en cada foto según la IA, y una página de texto que se pone
    detrás de su foto. None en las que no tengan.
    """
    if not rutas:
        raise ValueError("no hay imágenes que convertir")
    esquinas = esquinas or [None] * len(rutas)
    datos = datos or [None] * len(rutas)
    paginas = []
    for ruta, esquina, pagina_datos in zip(rutas, esquinas, datos):
        paginas.append(_como_escaneado(ruta, esquina))
        if pagina_datos is not None:
            paginas.append(_pagina_de_datos(pagina_datos))
    salida = io.BytesIO()
    paginas[0].save(
        salida, format="PDF", save_all=True, append_images=paginas[1:], resolution=150
    )
    return salida.getvalue()
