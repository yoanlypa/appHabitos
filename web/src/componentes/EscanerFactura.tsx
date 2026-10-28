/**
 * Escanear un ticket y anotarlo como gasto.
 *
 * Tres pasos: foto → lectura → formulario ya relleno → guardar. Lo leído se
 * enseña antes de anotarlo a propósito: si el modelo leyó 234,00 donde ponía
 * 23,40, se ve aquí y no al cuadrar el mes.
 *
 * La foto se reduce en el navegador antes de subirla (1600 px de lado y
 * JPEG). Una foto de iPhone pesa 4-8 MB; así sube en un segundo con datos
 * móviles y el modelo la lee igual de bien. Tampoco hace falta recortar los
 * bordes: el modelo lee el ticket aunque esté torcido o con la mesa detrás.
 */
import { useRef, useState } from 'react'
import { confirmarGastoDeFactura, escanearFactura, type TicketLeido } from '../api'
import { iso } from '../utiles'

type Props = {
  token: string
  onGuardado: () => void
  onError: (e: unknown) => void
}

const LADO_MAXIMO = 1600

async function reducir(fichero: File): Promise<Blob> {
  const bitmap = await createImageBitmap(fichero).catch(() => null)
  // Si el navegador no sabe abrirla (HEIC en algunos), se manda tal cual.
  if (!bitmap) return fichero
  const escala = Math.min(1, LADO_MAXIMO / Math.max(bitmap.width, bitmap.height))
  const lienzo = document.createElement('canvas')
  lienzo.width = Math.round(bitmap.width * escala)
  lienzo.height = Math.round(bitmap.height * escala)
  lienzo.getContext('2d')!.drawImage(bitmap, 0, 0, lienzo.width, lienzo.height)
  bitmap.close()
  return new Promise((resolver) =>
    lienzo.toBlob((b) => resolver(b ?? fichero), 'image/jpeg', 0.85),
  )
}

export function EscanerFactura({ token, onGuardado, onError }: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const [leyendo, setLeyendo] = useState(false)
  const [vista, setVista] = useState<string | null>(null)
  const [leido, setLeido] = useState<TicketLeido | null>(null)
  const [concepto, setConcepto] = useState('')
  const [importe, setImporte] = useState('')
  const [fecha, setFecha] = useState(iso(new Date()))
  const [guardando, setGuardando] = useState(false)

  function cerrar() {
    if (vista) URL.revokeObjectURL(vista)
    setVista(null)
    setLeido(null)
  }

  async function elegida(e: React.ChangeEvent<HTMLInputElement>) {
    const fichero = e.target.files?.[0]
    e.target.value = '' // para poder volver a elegir la misma
    if (!fichero) return
    setLeyendo(true)
    try {
      const imagen = await reducir(fichero)
      const resultado = await escanearFactura(token, imagen)
      setVista(URL.createObjectURL(imagen))
      setLeido(resultado)
      setConcepto(resultado.concepto)
      setImporte(resultado.total ? resultado.total.replace('.', ',') : '')
      setFecha(resultado.fecha ?? iso(new Date()))
    } catch (err) {
      onError(err)
    } finally {
      setLeyendo(false)
    }
  }

  const importeLimpio = importe.replace(/\s|€/g, '').replace(/\./g, '').replace(',', '.')
  const importeValido = /^\d+(\.\d{1,2})?$/.test(importeLimpio) && Number(importeLimpio) > 0

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    if (!leido || !importeValido) return
    setGuardando(true)
    try {
      await confirmarGastoDeFactura(token, leido.factura_id, {
        concepto: concepto.trim(),
        importe: importeLimpio,
        fecha,
      })
      cerrar()
      onGuardado()
    } catch (err) {
      onError(err)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <>
      {/* capture abre directamente la cámara trasera en el móvil. */}
      <input
        ref={entrada}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => void elegida(e)}
      />
      <button
        type="button"
        className="escanear"
        disabled={leyendo}
        onClick={() => entrada.current?.click()}
      >
        {leyendo ? 'Leyendo el ticket…' : '📷 Escanear ticket'}
      </button>

      {leido && (
        <div className="modal-fondo" role="dialog" aria-modal="true" aria-label="Gasto escaneado">
          <form className="modal" onSubmit={guardar}>
            <h3>Gasto del ticket</h3>
            {vista && <img className="ticket-vista" src={vista} alt="Foto del ticket" />}
            {!leido.total && (
              <p className="error">No he leído el total con seguridad: escríbelo tú.</p>
            )}

            <label>
              Concepto
              <input value={concepto} onChange={(e) => setConcepto(e.target.value)} />
            </label>
            <label>
              Importe (€)
              <input
                inputMode="decimal"
                value={importe}
                onChange={(e) => setImporte(e.target.value)}
                placeholder="23,40"
                autoFocus={!leido.total}
              />
            </label>
            <label>
              Fecha del ticket
              <input
                type="date"
                value={fecha}
                max={iso(new Date())}
                onChange={(e) => setFecha(e.target.value)}
              />
            </label>
            {!leido.fecha && (
              <p className="error">No he leído la fecha: he puesto hoy. Cámbiala si es de otro día.</p>
            )}
            {leido.iva && (
              <p className="ayuda">IVA leído: {leido.iva.replace('.', ',')} €</p>
            )}

            <div className="botones">
              <button type="button" className="enlace" onClick={cerrar}>
                Cancelar
              </button>
              <button type="submit" disabled={!importeValido || guardando}>
                {guardando ? 'Guardando…' : 'Anotar gasto'}
              </button>
            </div>
          </form>
        </div>
      )}
    </>
  )
}
