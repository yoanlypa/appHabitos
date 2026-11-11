"""Abrir un Excel (.xlsx) y devolver sus celdas como texto. No sabe qué es un gasto.

Está en `nucleo/` por lo mismo que `paginas_pdf.py`: es una librería de
fuera (openpyxl) para un formato de fichero. Qué columnas hacen falta y qué
se acepta de ellas lo decide `dominio/importacion.py`, igual que con un CSV.
"""
import io
from datetime import date, datetime
from decimal import Decimal


class HojaNoLegible(ValueError):
    """El fichero no es un Excel que se pueda abrir."""


# Un Excel de movimientos hecho a mano no llega ni de lejos. El tope es para
# no recorrer una hoja con un millón de filas "usadas" por un formato raro.
_FILAS_MAXIMAS = 2000


def _a_texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, bool):
        return "si" if valor else "no"
    if isinstance(valor, float):
        # 2.75 guardado como 2.7500000000000004: con str() saldría tal cual.
        # Se redondea el ruido, no los decimales: 2,755 tiene que llegar como
        # 2,755 para que quien valida lo rechace en vez de inventarse 2,76.
        return format(Decimal(str(round(valor, 6))).normalize(), "f")
    return str(valor).strip()


def filas_de_xlsx(datos: bytes) -> list[list[str]]:
    """Las filas de la primera hoja, cada celda como texto."""
    try:
        from openpyxl import load_workbook

        libro = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl lanza de todo según cómo esté roto
        raise HojaNoLegible("no he podido abrir ese Excel") from exc
    try:
        hoja = libro.worksheets[0]
        filas = []
        for numero, fila in enumerate(hoja.iter_rows(values_only=True)):
            if numero >= _FILAS_MAXIMAS:
                break
            filas.append([_a_texto(celda) for celda in fila])
        return filas
    except Exception as exc:
        raise HojaNoLegible("no he podido leer ese Excel") from exc
    finally:
        libro.close()
