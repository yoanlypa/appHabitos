/**
 * Un trabajo o un gasto en una línea. La misma en Inicio, Finanzas y la
 * ficha del cliente: que un movimiento se vea igual en todas partes es lo que
 * hace que se reconozca sin leer.
 *
 * El redondel de la izquierda dice de un vistazo si el dinero entra, sale o
 * está por cobrar. Tocar la fila la abre para editarla; cobrar y ver el
 * ticket tienen su botón propio y no abren nada.
 */
import { ArrowDownLeft, ArrowUpRight, Check, Clock, Hammer, Landmark, ReceiptText, StickyNote } from 'lucide-react'
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
  /**
   * Elegir el trabajo sin abrir el movimiento: con el botoncito de debajo del
   * concepto o con el clic derecho (mantener pulsado en Android).
   */
  onTrabajo?: () => void
  /** Modo selección: la fila lleva casilla y tocarla la marca en vez de abrirla. */
  seleccionado?: boolean
  /** Algo más a la derecha (el desplegable de cliente en "Por cobrar"). */
  children?: ReactNode
}

function estado(a: Apunte, conObra = true) {
  if (a.tipo === 'nota') return 'Nota'
  // De un trabajo, lo que más dice es de cuál.
  // Si la fila ya lleva el botón del trabajo, no se repite aquí.
  const obra = conObra && a.trabajo_titulo ? ` · ${a.trabajo_titulo}` : ''
  if (a.tipo === 'gasto') return `${a.factura_id ? 'Gasto con ticket' : 'Gasto'}${obra}`
  const cobro = a.pendiente ? 'Pendiente de cobro' : 'Cobrado'
  return `${a.factura_emitida ? `${cobro} con factura` : cobro}${obra}`
}

/** La marca de lo que va a la gestoría: "Facturado" en un trabajo, "Gestoría" en un gasto. */
function MarcaGestoria({ apunte: a }: { apunte: Apunte }) {
  if (!a.gestoria) return null
  return (
    <span className="marca-gestoria" title="Va a la gestoría">
      <Landmark size={11} />
      Gestoría
    </span>
  )
}

export function FilaMovimiento({
  apunte: a,
  detalle,
  onAbrir,
  onCobrar,
  onTicket,
  onTrabajo,
  seleccionado,
  children,
}: Props) {
  const clase = a.tipo === 'gasto' ? 'gasto' : a.tipo === 'nota' ? '' : a.pendiente ? 'pendiente' : 'trabajo'
  const Icono =
    a.tipo === 'gasto' ? ArrowUpRight : a.tipo === 'nota' ? StickyNote : a.pendiente ? Clock : ArrowDownLeft

  return (
    <li
      className={[
        'fila movimiento',
        onAbrir ? 'tocable' : '',
        seleccionado ? 'seleccionada' : '',
      ].join(' ')}
      onClick={onAbrir}
      onContextMenu={
        onTrabajo && a.tipo !== 'nota'
          ? (e) => {
              e.preventDefault()
              onTrabajo()
            }
          : undefined
      }
      role={onAbrir ? 'button' : undefined}
      tabIndex={onAbrir ? 0 : undefined}
      onKeyDown={(e) => {
        if (onAbrir && e.key === 'Enter' && e.target === e.currentTarget) onAbrir()
      }}
    >
      {seleccionado !== undefined ? (
        <span className={seleccionado ? 'marca puesta' : 'marca'} aria-hidden="true">
          <Check size={14} strokeWidth={3} />
        </span>
      ) : (
        <span className={`insignia ${clase}`}>
          <Icono size={18} />
        </span>
      )}
      <span className="principal">
        {a.concepto}
        <small>
          {detalle ?? estado(a, !onTrabajo)}
          <MarcaGestoria apunte={a} />
        </small>
        {onTrabajo && a.tipo !== 'nota' && seleccionado === undefined && (
          <button
            type="button"
            className={a.trabajo_id ? 'chip-trabajo puesto' : 'chip-trabajo'}
            title="Elegir el trabajo (o clic derecho en la fila)"
            onClick={(e) => {
              e.stopPropagation()
              onTrabajo()
            }}
          >
            <Hammer size={12} />
            {a.trabajo_titulo ?? 'Asignar trabajo'}
          </button>
        )}
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
