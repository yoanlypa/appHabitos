/** Formatos compartidos por todas las pantallas. */

const EUROS = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' })

export function euros(valor: string | number) {
  return EUROS.format(Number(valor))
}

/** Cómo se llama cada tipo de apunte en la lista. */
export function etiqueta(tipo: string) {
  if (tipo === 'gasto') return 'gasto'
  if (tipo === 'nota') return 'nota'
  return 'cobrado'
}

/** YYYY-MM-DD, que es lo que espera la API. "sv-SE" lo da tal cual. */
export function iso(fecha: Date) {
  return fecha.toLocaleDateString('sv-SE')
}

export const MESES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
]

/** Lunes primero, que es como se mira un calendario aquí. */
export const DIAS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']

export function fechaCorta(isoFecha: string) {
  const [, m, d] = isoFecha.split('-').map(Number)
  return `${d} ${MESES[m - 1].slice(0, 3)}`
}

export function hhmm(hora: string | null) {
  return hora ? hora.slice(0, 5) : null
}

/** Cuánto lleva algo sin cobrarse, para poder decir "hace 3 semanas". */
export function antiguedad(isoFecha: string) {
  const [a, m, d] = isoFecha.split('-').map(Number)
  const entonces = new Date(a, m - 1, d)
  const dias = Math.floor((Date.now() - entonces.getTime()) / 86400000)
  if (dias <= 0) return 'hoy'
  if (dias === 1) return 'ayer'
  if (dias < 7) return `hace ${dias} días`
  if (dias < 30) return `hace ${Math.floor(dias / 7)} semanas`
  if (dias < 365) return `hace ${Math.floor(dias / 30)} meses`
  return 'hace más de un año'
}
