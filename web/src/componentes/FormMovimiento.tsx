/**
 * Añadir o editar un trabajo o un gasto, con todos sus campos a la vista.
 *
 * El mismo formulario para los dos casos: abrir uno ya hecho es lo que se
 * hace para corregirlo, y tener que aprender dos pantallas para lo mismo
 * estorba. Borrar va aquí dentro y pide confirmación: un botón de borrar en
 * cada fila de una lista larga se toca sin querer al hacer scroll.
 *
 * Si el gasto tiene ticket, se avisa de que borrarlo se lleva la foto.
 */
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { Apunte, DatosMovimiento } from '../api'
import { confirmar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { aImporte, iso } from '../utiles'

type Props = {
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  /** Para uno nuevo: si se abre desde el filtro de gastos, empieza en gasto. */
  tipoInicial?: 'trabajo' | 'gasto'
  onGuardar: (datos: DatosMovimiento) => Promise<void>
  onBorrar?: () => Promise<void>
  onCerrar: () => void
}

const TIPOS = [
  { id: 'trabajo', nombre: 'Trabajo (entra)' },
  { id: 'gasto', nombre: 'Gasto (sale)' },
] as const

export function FormMovimiento({ apunte, tipoInicial = 'trabajo', onGuardar, onBorrar, onCerrar }: Props) {
  const [tipo, setTipo] = useState<'trabajo' | 'gasto'>(
    apunte?.tipo === 'gasto' || apunte?.tipo === 'trabajo' ? apunte.tipo : tipoInicial,
  )
  const [concepto, setConcepto] = useState(apunte?.concepto ?? '')
  const [importe, setImporte] = useState(apunte ? apunte.importe.replace('.', ',') : '')
  const [fecha, setFecha] = useState(apunte?.fecha ?? iso(new Date()))
  const [pendiente, setPendiente] = useState(apunte?.pendiente ?? false)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  const importeLimpio = aImporte(importe)
  const valido = concepto.trim() !== '' && importeLimpio !== null && fecha !== ''

  async function hacer(accion: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await accion()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se ha podido guardar')
      setOcupado(false)
    }
  }

  function guardar(e: React.FormEvent) {
    e.preventDefault()
    if (!valido || !importeLimpio) return
    void hacer(() =>
      onGuardar({
        tipo,
        concepto: concepto.trim(),
        importe: importeLimpio,
        fecha,
        pendiente: tipo === 'trabajo' && pendiente,
      }),
    )
  }

  async function borrar() {
    if (!onBorrar || !apunte) return
    const si = await confirmar({
      titulo: `¿Borrar «${apunte.concepto}»?`,
      texto: apunte.factura_id
        ? 'Se borra también la foto del ticket. No se puede deshacer.'
        : 'No se puede deshacer.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (si) void hacer(onBorrar)
  }

  return (
    <Modal titulo={apunte ? 'Editar movimiento' : 'Nuevo movimiento'} onCerrar={onCerrar}>
      <form className="formulario" onSubmit={guardar}>
        <Segmentado opciones={TIPOS} valor={tipo} onCambio={setTipo} ancho etiqueta="Tipo" />

        <label className="campo">
          Concepto
          <input
            value={concepto}
            onChange={(e) => setConcepto(e.target.value)}
            placeholder={tipo === 'trabajo' ? 'Montaje armario Ana' : 'Gasolina'}
            autoFocus={!apunte}
          />
        </label>
        <div className="dos-campos">
          <label className="campo">
            Importe (€)
            <input
              inputMode="decimal"
              value={importe}
              onChange={(e) => setImporte(e.target.value)}
              placeholder="120,00"
            />
          </label>
          <label className="campo">
            Fecha
            <input
              type="date"
              value={fecha}
              max={iso(new Date())}
              onChange={(e) => setFecha(e.target.value)}
            />
          </label>
        </div>
        {tipo === 'trabajo' && (
          <label className="casilla">
            <input
              type="checkbox"
              checked={pendiente}
              onChange={(e) => setPendiente(e.target.checked)}
            />
            Pendiente de cobro
          </label>
        )}
        {importe && !importeLimpio && (
          <ErrorEnLinea>El importe no se entiende: escribe 120 o 45,50.</ErrorEnLinea>
        )}
        <ErrorEnLinea>{error}</ErrorEnLinea>

        <div className="botones">
          {apunte && onBorrar && (
            <button
              type="button"
              className="boton-icono peligro"
              onClick={() => void borrar()}
              disabled={ocupado}
              aria-label="Borrar"
              title="Borrar"
            >
              <Trash2 size={18} />
            </button>
          )}
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar} disabled={ocupado}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!valido || ocupado}>
              {ocupado ? 'Guardando…' : 'Guardar'}
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}
