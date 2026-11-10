/** Las piezas pequeñas que se repiten: cabecera de página, vacíos, cifras. */
import { CircleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** El título de cada pantalla, con sus botones a la derecha. */
export function Cabecera({
  titulo,
  subtitulo,
  children,
}: {
  titulo: string
  subtitulo?: ReactNode
  children?: ReactNode
}) {
  return (
    <header className="cabecera-pagina">
      <div>
        <h1>{titulo}</h1>
        {subtitulo && <p className="subtitulo">{subtitulo}</p>}
      </div>
      {children && <div className="cabecera-acciones">{children}</div>}
    </header>
  )
}

/** Lo que se enseña cuando no hay nada: dice qué falta y, si puede, cómo ponerlo. */
export function Vacio({
  icono: Icono,
  titulo,
  children,
}: {
  icono?: LucideIcon
  titulo?: string
  children?: ReactNode
}) {
  return (
    <div className="vacio">
      {Icono && <Icono size={28} strokeWidth={1.5} />}
      {titulo && <strong>{titulo}</strong>}
      {children}
    </div>
  )
}

/** Tres barras grises mientras llegan los datos: la página no da saltos. */
export function Esqueleto() {
  return (
    <div className="esqueleto" aria-label="Cargando">
      <i />
      <i />
      <i />
    </div>
  )
}

export function ErrorEnLinea({ children }: { children: ReactNode }) {
  if (!children) return null
  return (
    <p className="error" role="alert">
      <CircleAlert size={18} />
      <span>{children}</span>
    </p>
  )
}

/** Una cifra con su nombre. El punto de color dice de qué tipo es. */
export function Kpi({
  nombre,
  valor,
  tipo,
  nota,
}: {
  nombre: string
  valor: string
  tipo?: 'cobrado' | 'pendiente' | 'gasto' | 'neto'
  nota?: ReactNode
}) {
  return (
    <div className={tipo ? `kpi ${tipo}` : 'kpi'}>
      <dt>
        {tipo && <i aria-hidden="true" />}
        {nombre}
      </dt>
      <dd>{valor}</dd>
      {nota && <small>{nota}</small>}
    </div>
  )
}

/** Las iniciales en un redondel: una lista de personas se recorre mejor así. */
export function Avatar({ nombre, grande }: { nombre: string; grande?: boolean }) {
  const iniciales = nombre
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
  // El tono sale del nombre, así cada persona tiene siempre el mismo.
  let suma = 0
  for (const letra of nombre) suma = (suma * 31 + letra.charCodeAt(0)) % 360
  return (
    <span
      className={grande ? 'avatar grande' : 'avatar'}
      style={{ '--tono': suma } as React.CSSProperties}
      aria-hidden="true"
    >
      {iniciales}
    </span>
  )
}
