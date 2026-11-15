/**
 * Añadir o editar un cobro o un gasto, con todos sus campos a la vista.
 *
 * El mismo formulario para los dos casos: abrir uno ya hecho es lo que se
 * hace para corregirlo, y tener que aprender dos pantallas para lo mismo
 * estorba. Borrar va aquí dentro y pide confirmación: un botón de borrar en
 * cada fila de una lista larga se toca sin querer al hacer scroll.
 *
 * Cada movimiento dice de qué trabajo es (o que no es de ninguno): de eso, y
 * de si el trabajo está facturado, sale lo que va a la gestoría.
 *
 * Si tiene ticket o factura, se avisa de que borrarlo se lleva el papel.
 */
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { listarTrabajos, type Apunte, type DatosMovimiento, type Trabajo } from '../api'
import { confirmar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { aImporte, iso } from '../utiles'
import { DeQueTrabajo } from './DeQueTrabajo'

type Props = {
  token: string
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  /** Para uno nuevo: si se abre desde el filtro de gastos, empieza en gasto. */
  tipoInicial?: 'trabajo' | 'gasto'
  /** Para uno nuevo que ya se sabe de qué trabajo es (desde su ficha). */
  trabajoInicial?: number | null
  onGuardar: (datos: DatosMovimiento) => Promise<void>
  onBorrar?: () => Promise<void>
  onCerrar: () => void
}

const TIPOS = [
  { id: 'trabajo', nombre: 'Cobro (entra)' },
  { id: 'gasto', nombre: 'Gasto (sale)' },
] as const

export function FormMovimiento({
  token,
  apunte,
  tipoInicial = 'trabajo',
  trabajoInicial = null,
  onGuardar,
  onBorrar,
  onCerrar,
}: Props) {
  const [tipo, setTipo] = useState<'trabajo' | 'gasto'>(
    apunte?.tipo === 'gasto' || apunte?.tipo === 'trabajo' ? apunte.tipo : tipoInicial,
  )
  const [concepto, setConcepto] = useState(apunte?.concepto ?? '')
  const [importe, setImporte] = useState(apunte ? apunte.importe.replace('.', ',') : '')
  const [fecha, setFecha] = useState(apunte?.fecha ?? iso(new Date()))
  const [pendiente, setPendiente] = useState(apunte?.pendiente ?? false)
  const [trabajoId, setTrabajoId] = useState<number | null>(apunte?.trabajo_id ?? trabajoInicial)
  const [paraGestoria, setParaGestoria] = useState(apunte?.para_gestoria ?? false)
  const [trabajos, setTrabajos] = useState<Trabajo[]>([])
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelado = false
    // Si esto falla el formulario sigue valiendo: se guarda sin trabajo y
    // se asigna después. No merece tapar el formulario con un error.
    listarTrabajos(token)
      .then((lista) => {
        if (!cancelado) setTrabajos(lista.map((t) => t.trabajo))
      })
      .catch(() => {})
    return () => {
      cancelado = true
    }
  }, [token])

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
        trabajo_id: trabajoId,
        // La marca a mano solo vale para lo suelto; el backend también lo limpia.
        para_gestoria: trabajoId === null && paraGestoria,
      }),
    )
  }

  async function borrar() {
    if (!onBorrar || !apunte) return
    const si = await confirmar({
      titulo: `¿Borrar «${apunte.concepto}»?`,
      texto:
        (apunte.factura_id ? 'Se borra también su factura o la foto del ticket. ' : '') +
        'No se puede deshacer.',
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
            placeholder={tipo === 'trabajo' ? 'Primer pago reforma' : 'Material'}
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

        <DeQueTrabajo
          trabajos={trabajos}
          trabajoId={trabajoId}
          onTrabajo={setTrabajoId}
          paraGestoria={paraGestoria}
          onParaGestoria={setParaGestoria}
        />

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
