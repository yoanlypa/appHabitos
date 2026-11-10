/**
 * Escanear un ticket y anotarlo como gasto.
 *
 * También acepta un PDF (la factura que llega por email): va tal cual, sin
 * reducir, y el backend lo pinta para leerlo.
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
import { Camera, FileUp } from 'lucide-react'
import { useRef, useState } from 'react'
import {
  confirmarFacturaEmitida,
  confirmarGastoDeFactura,
  escanearFactura,
  type TicketLeido,
} from '../api'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea } from '../ui/piezas'
import { euros, fechaCorta, iso } from '../utiles'

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
  const entradaPdf = useRef<HTMLInputElement>(null)
  const [leyendo, setLeyendo] = useState(false)
  const [vista, setVista] = useState<string | null>(null)
  const [leido, setLeido] = useState<TicketLeido | null>(null)
  const [concepto, setConcepto] = useState('')
  const [importe, setImporte] = useState('')
  const [fecha, setFecha] = useState(iso(new Date()))
  const [guardando, setGuardando] = useState(false)
  // Solo para facturas propias: ya cobrada, y de qué trabajo es ('' = nuevo).
  const [cobrada, setCobrada] = useState(false)
  const [trabajo, setTrabajo] = useState('')

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
      // Un PDF (la factura del email) va tal cual: ya es un documento limpio.
      const esPdf = fichero.type === 'application/pdf' || fichero.name.toLowerCase().endsWith('.pdf')
      const imagen = esPdf ? new Blob([fichero], { type: 'application/pdf' }) : await reducir(fichero)
      const resultado = await escanearFactura(token, imagen)
      setVista(esPdf ? null : URL.createObjectURL(imagen))
      setLeido(resultado)
      setConcepto(resultado.concepto)
      const cifra = resultado.emitida ? resultado.a_cobrar : resultado.total
      setImporte(cifra ? cifra.replace('.', ',') : '')
      setCobrada(false)
      // Un solo trabajo posible: se propone; con varios, que elija.
      setTrabajo(resultado.candidatos.length === 1 ? String(resultado.candidatos[0].id) : '')
      setFecha(resultado.fecha ?? iso(new Date()))
    } catch (err) {
      onError(err)
    } finally {
      setLeyendo(false)
    }
  }

  const importeLimpio = importe.replace(/\s|€/g, '').replace(/\./g, '').replace(',', '.')
  const importeValido =
    (leido?.emitida && trabajo !== '') ||
    (/^\d+(\.\d{1,2})?$/.test(importeLimpio) && Number(importeLimpio) > 0)

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    if (!leido || !importeValido) return
    setGuardando(true)
    try {
      if (leido.emitida) {
        await confirmarFacturaEmitida(token, leido.factura_id, {
          apunte_id: trabajo ? Number(trabajo) : null,
          cobrada,
          concepto: concepto.trim(),
          importe: importeLimpio,
          fecha,
        })
      } else {
        await confirmarGastoDeFactura(token, leido.factura_id, {
          concepto: concepto.trim(),
          importe: importeLimpio,
          fecha,
        })
      }
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
      <input
        ref={entradaPdf}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        onChange={(e) => void elegida(e)}
      />
      <div className="escaner-botones">
        <button
          type="button"
          className="boton secundario"
          disabled={leyendo}
          onClick={() => entrada.current?.click()}
        >
          <Camera size={18} />
          {leyendo ? 'Leyendo…' : 'Escanear ticket'}
        </button>
        <button
          type="button"
          className="boton secundario"
          disabled={leyendo}
          onClick={() => entradaPdf.current?.click()}
        >
          <FileUp size={18} />
          Subir PDF
        </button>
      </div>

      {leido && (
        <Modal
          titulo={
            leido.emitida
              ? `Factura tuya${leido.cliente ? ` a ${leido.cliente}` : ''}`
              : 'Gasto del ticket'
          }
          onCerrar={cerrar}
          cierreFacil={false}
        >
          <form className="formulario" onSubmit={guardar}>
            {leido.emitida && (
              <p className="ayuda">Se anota como trabajo (dinero que entra), no como gasto.</p>
            )}
            {vista ? (
              <img className="ticket-vista" src={vista} alt="Foto del ticket" />
            ) : (
              <p className="ayuda">Factura en PDF leída.</p>
            )}
            {!leido.total && (
              <ErrorEnLinea>No he leído el total con seguridad: escríbelo tú.</ErrorEnLinea>
            )}

            {leido.emitida && leido.candidatos.length > 0 && (
              <label className="campo">
                ¿De qué trabajo es?
                <select value={trabajo} onChange={(e) => setTrabajo(e.target.value)}>
                  <option value="">Un trabajo nuevo</option>
                  {leido.candidatos.map((c) => (
                    <option key={c.id} value={c.id}>
                      {fechaCorta(c.fecha)} · {c.concepto} · {euros(c.importe)}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {leido.emitida && trabajo !== '' && (
              <p className="ayuda">Se cuelga de ese trabajo: no se cuenta dos veces.</p>
            )}
            <label className="campo" hidden={leido.emitida && trabajo !== ''}>
              Concepto
              <input value={concepto} onChange={(e) => setConcepto(e.target.value)} />
            </label>
            <div className="dos-campos" hidden={leido.emitida && trabajo !== ''}>
              <label className="campo">
                {leido.emitida ? 'A cobrar (€)' : 'Importe (€)'}
                <input
                  inputMode="decimal"
                  value={importe}
                  onChange={(e) => setImporte(e.target.value)}
                  placeholder="23,40"
                  autoFocus={!leido.total}
                />
              </label>
              <label className="campo">
                {leido.emitida ? 'Fecha de la factura' : 'Fecha del ticket'}
                <input
                  type="date"
                  value={fecha}
                  max={iso(new Date())}
                  onChange={(e) => setFecha(e.target.value)}
                />
              </label>
            </div>
            {!leido.fecha && (
              <ErrorEnLinea>
                No he leído la fecha: he puesto hoy. Cámbiala si es de otro día.
              </ErrorEnLinea>
            )}
            {leido.emitida && (
              <label className="casilla">
                <input
                  type="checkbox"
                  checked={cobrada}
                  onChange={(e) => setCobrada(e.target.checked)}
                />
                Ya está cobrada
              </label>
            )}
            {leido.iva && <p className="ayuda">IVA leído: {leido.iva.replace('.', ',')} €</p>}

            <div className="botones">
              <span className="derecha">
                <button type="button" className="boton secundario" onClick={cerrar}>
                  Cancelar
                </button>
                <button type="submit" className="boton" disabled={!importeValido || guardando}>
                  {guardando ? 'Guardando…' : leido.emitida ? 'Anotar factura' : 'Anotar gasto'}
                </button>
              </span>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
