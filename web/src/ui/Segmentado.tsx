/** Dos o tres opciones de las que siempre hay una elegida. */
type Opcion<T extends string> = { id: T; nombre: string; cuenta?: number }

type Props<T extends string> = {
  opciones: readonly Opcion<T>[]
  valor: T
  onCambio: (valor: T) => void
  /** Ocupa todo el ancho y reparte el sitio a partes iguales. */
  ancho?: boolean
  etiqueta?: string
}

export function Segmentado<T extends string>({ opciones, valor, onCambio, ancho, etiqueta }: Props<T>) {
  return (
    <div className={ancho ? 'segmentado ancho' : 'segmentado'} role="tablist" aria-label={etiqueta}>
      {opciones.map((o) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          aria-selected={valor === o.id}
          className={valor === o.id ? 'activa' : ''}
          onClick={() => onCambio(o.id)}
        >
          {o.nombre}
          {o.cuenta !== undefined && <span className="contador">{o.cuenta}</span>}
        </button>
      ))}
    </div>
  )
}
