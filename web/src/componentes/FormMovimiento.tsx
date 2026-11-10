/**
 * Añadir o editar un trabajo o un gasto, con todos sus campos a la vista.
 *
 * El mismo formulario para los dos casos: abrir uno ya hecho es lo que se
 * hace para corregirlo, y tener que aprender dos pantallas para lo mismo
 * estorba. Borrar va aquí dentro y pide confirmación: un botón de borrar en
 * cada fila de una lista larga se toca sin querer al hacer scroll.
 *
 * Un gasto dice de qué trabajo es (o que no es de ninguno) y un trabajo dice
 * si lo factura Yoa: de eso sale lo que va a la gestoría. Al abrir un trabajo
 * ya hecho se ven debajo sus gastos y lo que queda después de ellos, que es
 * la cuenta que de verdad importa de un trabajo.
 *
 * Si el gasto tiene ticket, se avisa de que borrarlo se lleva la foto.
 */
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  fichaTrabajo,
  trabajosParaElegir,
  type Apunte,
  type DatosMovimiento,
  type FichaTrabajo,
} from '../api'
import { confirmar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { aImporte, euros, fechaCorta, iso } from '../utiles'
import { DeQueTrabajo } from './DeQueTrabajo'

type Props = {
  token: string
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  /** Para uno nuevo: si se abre desde el filtro de gastos, empieza en gasto. */
  tipoInicial?: 'trabajo' | 'gasto'
  /** Para un gasto nuevo que ya se sabe de qué trabajo es. */
  trabajoInicial?: number | null
  onGuardar: (datos: DatosMovimiento) => Promise<void>
  onBorrar?: () => Promise<void>
  /** "Añadir un gasto a este trabajo", desde la ficha de un trabajo. */
  onAnadirGasto?: (trabajo: Apunte) => void
  onCerrar: () => void
}

const TIPOS = [
  { id: 'trabajo', nombre: 'Trabajo (entra)' },
  { id: 'gasto', nombre: 'Gasto (sale)' },
] as const

export function FormMovimiento({
  token,
  apunte,
  tipoInicial = 'trabajo',
  trabajoInicial = null,
  onGuardar,
  onBorrar,
  onAnadirGasto,
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
  const [facturado, setFacturado] = useState(apunte?.facturado ?? false)
  const [paraGestoria, setParaGestoria] = useState(apunte?.para_gestoria ?? false)
  const [trabajos, setTrabajos] = useState<Apunte[]>([])
  const [ficha, setFicha] = useState<FichaTrabajo | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  const esTrabajoHecho = apunte?.tipo === 'trabajo'
  const idApunte = apunte?.id

  useEffect(() => {
    let cancelado = false
    // Si esto falla el formulario sigue valiendo: se guarda sin trabajo y
    // se asigna después. No merece tapar el formulario con un error.
    trabajosParaElegir(token)
      .then((lista) => {
        // Un trabajo no cuelga de sí mismo, por si se le cambia el tipo.
        if (!cancelado) setTrabajos(lista.filter((t) => t.id !== idApunte))
      })
      .catch(() => {})
    if (esTrabajoHecho && idApunte !== undefined) {
      fichaTrabajo(token, idApunte)
        .then((f) => {
          if (!cancelado) setFicha(f)
        })
        .catch(() => {})
    }
    return () => {
      cancelado = true
    }
  }, [token, idApunte, esTrabajoHecho])

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
        // Cada marca solo vale para su tipo; el backend también lo limpia.
        trabajo_id: tipo === 'gasto' ? trabajoId : null,
        facturado: tipo === 'trabajo' && facturado,
        para_gestoria: tipo === 'gasto' && trabajoId === null && paraGestoria,
      }),
    )
  }

  async function borrar() {
    if (!onBorrar || !apunte) return
    const gastos = ficha?.gastos.length ?? 0
    const si = await confirmar({
      titulo: `¿Borrar «${apunte.concepto}»?`,
      texto:
        (apunte.factura_id ? 'Se borra también su factura o la foto del ticket. ' : '') +
        (gastos === 1
          ? 'Su gasto se queda, pero sin trabajo. '
          : gastos > 1
            ? `Sus ${gastos} gastos se quedan, pero sin trabajo. `
            : '') +
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

        {tipo === 'trabajo' ? (
          <>
            <label className="casilla">
              <input
                type="checkbox"
                checked={pendiente}
                onChange={(e) => setPendiente(e.target.checked)}
              />
              Pendiente de cobro
            </label>
            <label className="casilla">
              <input
                type="checkbox"
                // Con la factura colgada está facturado se diga lo que se diga.
                checked={facturado || Boolean(apunte?.factura_emitida)}
                disabled={Boolean(apunte?.factura_emitida)}
                onChange={(e) => setFacturado(e.target.checked)}
              />
              <span>
                Lo facturo yo
                <small>
                  {apunte?.factura_emitida
                    ? 'Tiene tu factura colgada.'
                    : 'Va a la gestoría con sus gastos. Déjalo sin marcar si lo factura otra empresa.'}
                </small>
              </span>
            </label>
          </>
        ) : (
          <DeQueTrabajo
            trabajos={trabajos}
            trabajoId={trabajoId}
            onTrabajo={setTrabajoId}
            paraGestoria={paraGestoria}
            onParaGestoria={setParaGestoria}
          />
        )}

        {tipo === 'trabajo' && ficha && apunte && (
          <section className="gastos-del-trabajo">
            <h3>Gastos de este trabajo</h3>
            {ficha.gastos.length === 0 ? (
              <p className="ayuda">Todavía no tiene ninguno.</p>
            ) : (
              <>
                <ul>
                  {ficha.gastos.map((g) => (
                    <li key={g.id}>
                      <span>
                        {g.concepto} <small>{fechaCorta(g.fecha)}</small>
                      </span>
                      <b>−{euros(g.importe)}</b>
                    </li>
                  ))}
                </ul>
                <dl>
                  <div>
                    <dt>Gastos</dt>
                    <dd>{euros(ficha.total_gastos)}</dd>
                  </div>
                  <div className="queda">
                    <dt>Te queda</dt>
                    <dd>{euros(ficha.beneficio)}</dd>
                  </div>
                </dl>
              </>
            )}
            {onAnadirGasto && (
              <button
                type="button"
                className="boton suave pequeno"
                onClick={() => onAnadirGasto(apunte)}
                disabled={ocupado}
              >
                <Plus size={15} />
                Añadir un gasto a este trabajo
              </button>
            )}
          </section>
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
