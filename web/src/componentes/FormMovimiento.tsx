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
import { useState } from 'react'
import type { Apunte, DatosMovimiento } from '../api'
import { iso } from '../utiles'

type Props = {
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  /** Para uno nuevo: si se abre desde el filtro de gastos, empieza en gasto. */
  tipoInicial?: 'trabajo' | 'gasto'
  onGuardar: (datos: DatosMovimiento) => Promise<void>
  onBorrar?: () => Promise<void>
  onCerrar: () => void
}

/** "1.234,50" o "12,5" → "1234.50" / "12.5"; null si no es un importe. */
function aImporte(texto: string): string | null {
  const limpio = texto.replace(/\s|€/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.')
  return /^\d+(\.\d{1,2})?$/.test(limpio) && Number(limpio) > 0 ? limpio : null
}

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

  function borrar() {
    if (!onBorrar || !apunte) return
    const aviso = apunte.factura_id
      ? `¿Borrar «${apunte.concepto}»? Se borra también la foto del ticket.`
      : `¿Borrar «${apunte.concepto}»?`
    if (confirm(aviso)) void hacer(onBorrar)
  }

  return (
    <div className="modal-fondo" role="dialog" aria-modal="true" aria-label="Movimiento">
      <form className="modal" onSubmit={guardar}>
        <h3>{apunte ? 'Editar' : 'Añadir'}</h3>

        <div className="pestanas">
          <button
            type="button"
            className={tipo === 'trabajo' ? 'activa' : ''}
            onClick={() => setTipo('trabajo')}
          >
            Trabajo (entra)
          </button>
          <button
            type="button"
            className={tipo === 'gasto' ? 'activa' : ''}
            onClick={() => setTipo('gasto')}
          >
            Gasto (sale)
          </button>
        </div>

        <label>
          Concepto
          <input
            value={concepto}
            onChange={(e) => setConcepto(e.target.value)}
            placeholder={tipo === 'trabajo' ? 'Montaje armario Ana' : 'Gasolina'}
            autoFocus={!apunte}
          />
        </label>
        <label>
          Importe (€)
          <input
            inputMode="decimal"
            value={importe}
            onChange={(e) => setImporte(e.target.value)}
            placeholder="120,00"
          />
        </label>
        <label>
          Fecha
          <input type="date" value={fecha} max={iso(new Date())} onChange={(e) => setFecha(e.target.value)} />
        </label>
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
        {importe && !importeLimpio && <p className="error">El importe no se entiende: 120 o 45,50.</p>}
        {error && <p className="error">{error}</p>}

        <div className="botones">
          {apunte && onBorrar ? (
            <button type="button" className="enlace borrar-enlace" onClick={borrar} disabled={ocupado}>
              Borrar
            </button>
          ) : (
            <span />
          )}
          <span className="botones-derecha">
            <button type="button" className="enlace" onClick={onCerrar} disabled={ocupado}>
              Cancelar
            </button>
            <button type="submit" disabled={!valido || ocupado}>
              {ocupado ? 'Guardando…' : 'Guardar'}
            </button>
          </span>
        </div>
      </form>
    </div>
  )
}
