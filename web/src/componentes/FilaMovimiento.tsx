/**
 * Un trabajo o un gasto en una línea. La misma en Inicio, Finanzas y la
 * ficha del cliente: que un movimiento se vea igual en todas partes es lo que
 * hace que se reconozca sin leer.
 *
 * El redondel de la izquierda dice de un vistazo si el dinero entra, sale o
 * está por cobrar. Tocar la fila la abre para editarla; cobrar y ver el
 * ticket tienen su botón propio y no abren nada.
 */
import { ArrowDownLeft, ArrowUpRight, Clock, Landmark, ReceiptText, StickyNote } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Apunte } from '../api'
import { euros } from '../utiles'

type Props = {
  apunte: Apunte
  /** Lo que va debajo del concepto. Si no se da, el estado ("Cobrado"...). */
  detalle?: ReactNode
  onAbrir?: () => void
  onCobrar?: () => void
  onTicket?: () => void
  /** Algo más a la derecha (el desplegable de cliente en "Por cobrar"). */
  children?: ReactNode
}

function estado(a: Apunte) {
  if (a.tipo === 'nota') return 'Nota'
  if (a.tipo === 'gasto') {
    // De un trabajo, lo que más dice es de cuál; del suelto, que es un gasto.
    const que = a.trabajo_concepto ?? 'Gasto'
    return a.factura_id ? `${que} · con ticket` : que
  }
  const cobro = a.pendiente ? 'Pendiente de cobro' : 'Cobrado'
  return a.factura_emitida ? `${cobro} · con factura` : cobro
}

/** La marca de lo que va a la gestoría: "Facturado" en un trabajo, "Gestoría" en un gasto. */
function MarcaGestoria({ apunte: a }: { apunte: Apunte }) {
  if (!a.gestoria) return null
  return (
    <span className="marca-gestoria" title="Va a la gestoría">
      <Landmark size={11} />
      {a.tipo === 'trabajo' ? 'Facturado' : 'Gestoría'}
    </span>
  )
}

export function FilaMovimiento({ apunte: a, detalle, onAbrir, onCobrar, onTicket, children }: Props) {
  const clase = a.tipo === 'gasto' ? 'gasto' : a.tipo === 'nota' ? '' : a.pendiente ? 'pendiente' : 'trabajo'
  const Icono =
    a.tipo === 'gasto' ? ArrowUpRight : a.tipo === 'nota' ? StickyNote : a.pendiente ? Clock : ArrowDownLeft

  return (
    <li
      className={onAbrir ? 'fila movimiento tocable' : 'fila movimiento'}
      onClick={onAbrir}
      role={onAbrir ? 'button' : undefined}
      tabIndex={onAbrir ? 0 : undefined}
      onKeyDown={(e) => {
        if (onAbrir && e.key === 'Enter' && e.target === e.currentTarget) onAbrir()
      }}
    >
      <span className={`insignia ${clase}`}>
        <Icono size={18} />
      </span>
      <span className="principal">
        {a.concepto}
        <small>
          {detalle ?? estado(a)}
          <MarcaGestoria apunte={a} />
        </small>
      </span>
      {children}
      {a.factura_id && onTicket && (
        <button
          className="boton-icono"
          title="Ver el ticket en PDF"
          aria-label="Ver el ticket en PDF"
          onClick={(e) => {
            e.stopPropagation()
            onTicket()
          }}
        >
          <ReceiptText size={18} />
        </button>
      )}
      {/* Una nota no lleva dinero: enseñar "0,00 €" sería ruido. */}
      {a.tipo !== 'nota' && (
        <span className={`importe ${a.tipo === 'gasto' ? 'gasto' : ''}`}>
          {a.tipo === 'gasto' ? '−' : ''}
          {euros(a.importe)}
        </span>
      )}
      {a.pendiente && onCobrar && (
        <button
          className="boton pequeno cobrar"
          onClick={(e) => {
            e.stopPropagation()
            onCobrar()
          }}
        >
          Cobrar
        </button>
      )}
    </li>
  )
}
