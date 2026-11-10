/**
 * El mes en rejilla, de lunes a domingo. Lo usan la agenda y los hábitos.
 *
 * Solo sabe dibujar el mes y moverse por él: qué significa cada día (si
 * tiene citas, si el hábito se cumplió) se lo dice quien lo usa con `celda`.
 * Así los dos calendarios son el mismo y no pueden acabar pareciéndose
 * "casi".
 */
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { DIAS, MESES, iso } from '../utiles'

export type Celda = {
  clase?: string
  etiqueta?: string
  desactivado?: boolean
  pulsado?: boolean
  /** Lo que va dentro además del número: puntos, citas... */
  extra?: ReactNode
}

type Props = {
  anio: number
  mes: number // 1 = enero
  onMes: (anio: number, mes: number) => void
  celda: (fecha: string) => Celda
  onDia?: (fecha: string) => void
  /** Con celdas altas, para que quepan las citas dentro (agenda en el ordenador). */
  grande?: boolean
}

export function Calendario({ anio, mes, onMes, celda, onDia, grande }: Props) {
  const hoy = new Date()
  const hoyISO = iso(hoy)
  // Rejilla empezando en lunes: getDay() da 0 para domingo.
  const hueco = (new Date(anio, mes - 1, 1).getDay() + 6) % 7
  const cuantos = new Date(anio, mes, 0).getDate()
  // Huecos también al final, hasta completar la semana: sin ellos la última
  // fila de la rejilla se queda a medias y parece que falta un trozo.
  const cola = (7 - ((hueco + cuantos) % 7)) % 7
  const esteMes = anio === hoy.getFullYear() && mes === hoy.getMonth() + 1

  function saltar(pasos: number) {
    const d = new Date(anio, mes - 1 + pasos, 1)
    onMes(d.getFullYear(), d.getMonth() + 1)
  }

  return (
    <section className={grande ? 'calendario grande' : 'calendario'}>
      <header className="cal-cabecera">
        <h2>
          {MESES[mes - 1]} <span>{anio}</span>
        </h2>
        <div className="cal-mandos">
          {!esteMes && (
            <button
              className="boton secundario pequeno"
              onClick={() => onMes(hoy.getFullYear(), hoy.getMonth() + 1)}
            >
              Hoy
            </button>
          )}
          <button className="boton-icono" onClick={() => saltar(-1)} aria-label="Mes anterior">
            <ChevronLeft size={20} />
          </button>
          <button className="boton-icono" onClick={() => saltar(1)} aria-label="Mes siguiente">
            <ChevronRight size={20} />
          </button>
        </div>
      </header>

      <div className="cal-rejilla">
        {DIAS.map((d) => (
          <span key={d} className="cal-dia-nombre">
            {d}
          </span>
        ))}
        {Array.from({ length: hueco }, (_, i) => (
          <span key={`hueco-${i}`} className="cal-hueco" />
        ))}
        {Array.from({ length: cuantos }, (_, i) => {
          const fecha = iso(new Date(anio, mes - 1, i + 1))
          const c = celda(fecha)
          const clases = ['cal-dia']
          if (fecha === hoyISO) clases.push('hoy')
          if (c.clase) clases.push(c.clase)
          return (
            <button
              key={fecha}
              className={clases.join(' ')}
              disabled={c.desactivado}
              aria-pressed={c.pulsado}
              aria-label={c.etiqueta}
              onClick={() => onDia?.(fecha)}
            >
              <span className="cal-numero">{i + 1}</span>
              {c.extra}
            </button>
          )
        })}
        {Array.from({ length: cola }, (_, i) => (
          <span key={`cola-${i}`} className="cal-hueco" />
        ))}
      </div>
    </section>
  )
}
