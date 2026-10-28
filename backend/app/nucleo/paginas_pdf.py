"""Pintar las páginas de un PDF como imágenes. No sabe qué es una factura.

Las facturas que llegan por email (luz, Amazon, un proveedor) vienen en PDF,
y el lector de tickets y el PDF de salida trabajan con imágenes. Pasar cada
página a imagen deja un solo camino para todo, en vez de uno para fotos y
otro para PDF.

pypdfium2 trae el motor de Chrome para PDF dentro del paquete: no necesita
nada instalado en el servidor, que en Railway no lo hay.
"""
import pypdfium2 as pdfium
from PIL import Image

# 150 ppp: se lee la letra pequeña de una factura y la imagen no pesa megas.
_ESCALA = 150 / 72
# Una factura de verdad cabe en 2-3 páginas; un PDF de 80 páginas no es un
# ticket, y pintarlo entero colgaría el bot.
MAXIMO_PAGINAS = 4


class PdfNoLegible(ValueError):
    """El fichero no es un PDF que se pueda abrir (dañado o con contraseña)."""


def paginas(contenido: bytes, maximo: int = MAXIMO_PAGINAS) -> list[Image.Image]:
    try:
        documento = pdfium.PdfDocument(contenido)
    except pdfium.PdfiumError as exc:
        raise PdfNoLegible("no se puede abrir el PDF (¿dañado o con contraseña?)") from exc
    try:
        if len(documento) == 0:
            raise PdfNoLegible("el PDF no tiene páginas")
        return [
            documento[i].render(scale=_ESCALA).to_pil().convert("RGB")
            for i in range(min(len(documento), maximo))
        ]
    finally:
        documento.close()


def unir_en_una(imagenes: list[Image.Image], ancho_maximo: int = 1600) -> Image.Image:
    """Las páginas una debajo de otra, para que el lector las vea todas a la vez.

    El total y la fecha pueden estar en la segunda página; mandar solo la
    primera los perdería.
    """
    reducidas = []
    for imagen in imagenes:
        escala = min(1, ancho_maximo / imagen.width)
        reducidas.append(imagen.resize((int(imagen.width * escala), int(imagen.height * escala))))
    hoja = Image.new("RGB", (max(i.width for i in reducidas), sum(i.height for i in reducidas)), "white")
    y = 0
    for imagen in reducidas:
        hoja.paste(imagen, (0, y))
        y += imagen.height
    return hoja
