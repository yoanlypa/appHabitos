/**
 * De qué trabajo (obra) es un cobro o un gasto, y si va a la gestoría.
 *
 * Lo comparten el formulario de movimientos y el del ticket escaneado: la
 * pregunta es la misma y tiene que hacerse igual en los dos.
 *
 * Lo de un trabajo no se marca aparte: sigue a su trabajo, y aquí se dice qué
 * le toca ("va" o "no va") para que no haya que adivinarlo. Solo lo suelto
 * lleva casilla, porque ahí no hay trabajo que decida por él.
 */
import type { Trabajo } from '../api'

type Props = {
  trabajos: Trabajo[]
  trabajoId: number | null
  onTrabajo: (id: number | null) => void
  paraGestoria: boolean
  onParaGestoria: (va: boolean) => void
}

export function DeQueTrabajo({ trabajos, trabajoId, onTrabajo, paraGestoria, onParaGestoria }: Props) {
  const elegido = trabajos.find((t) => t.id === trabajoId)

  return (
    <>
      <label className="campo">
        ¿De qué trabajo es?
        <select
          value={trabajoId ?? ''}
          onChange={(e) => onTrabajo(e.target.value ? Number(e.target.value) : null)}
        >
          <option value="">De ninguno (general)</option>
          {trabajos.map((t) => (
            <option key={t.id} value={t.id}>
              {t.titulo}
              {t.cliente ? ` · ${t.cliente.nombre}` : ''}
              {t.facturado ? ' · facturado' : ''}
            </option>
          ))}
        </select>
      </label>

      {trabajoId === null ? (
        <label className="casilla">
          <input
            type="checkbox"
            checked={paraGestoria}
            onChange={(e) => onParaGestoria(e.target.checked)}
          />
          Va a la gestoría
        </label>
      ) : elegido?.facturado ? (
        <p className="nota-gestoria va">Va a la gestoría: ese trabajo lo facturas tú.</p>
      ) : (
        <p className="nota-gestoria">
          No va a la gestoría: ese trabajo no está facturado. Si lo facturas, irá solo.
        </p>
      )}
    </>
  )
}
