/** Formatos compartidos por todas las pantallas. */

// Con el punto de los miles también en 1.234,50 €: por defecto el español no
// lo pone hasta los cinco dígitos, y el bot sí. Que se lea igual en los dos.
const EUROS = new Intl.NumberFormat('es-ES', {
  style: 'currency',
  currency: 'EUR',
  useGrouping: 'always',
})

export function euros(valor: string | number) {
  return EUROS.format(Number(valor))
}

/**
 * Todos los días que ocupa algo, del primero al último incluidos.
 *
 * Hace falta para el calendario: una reforma del martes al jueves tiene que
 * poner punto en los tres días, o el miércoles parece libre.
 */
export function diasDelRango(desde: string, hasta: string | null): string[] {
  if (!hasta || hasta <= desde) return [desde]
  const dias: string[] = []
  const [a, m, d] = desde.split('-').map(Number)
  const cursor = new Date(a, m - 1, d)
  // Las fechas ISO se comparan como texto sin problema: "2026-09-02" es
  // menor que "2026-09-10" también en orden alfabético.
  while (iso(cursor) <= hasta) {
    dias.push(iso(cursor))
    cursor.setDate(cursor.getDate() + 1)
  }
  return dias
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

const DIAS_LARGOS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

function aFecha(isoFecha: string) {
  const [a, m, d] = isoFecha.split('-').map(Number)
  return new Date(a, m - 1, d)
}

/** "martes, 10 de noviembre": para los títulos, donde hay sitio. */
export function fechaLarga(isoFecha: string) {
  const f = aFecha(isoFecha)
  return `${DIAS_LARGOS[f.getDay()]}, ${f.getDate()} de ${MESES[f.getMonth()]}`
}

/**
 * "Hoy", "Mañana", "Ayer" o "vie 14 nov".
 *
 * Con el día de la semana delante a propósito: es lo que hace saltar a la
 * vista una cita puesta en el día que no es, igual que en el bot.
 */
export function diaRelativo(isoFecha: string) {
  const hoy = new Date()
  const f = aFecha(isoFecha)
  const dias = Math.round(
    (f.getTime() - new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate()).getTime()) / 86400000,
  )
  if (dias === 0) return 'Hoy'
  if (dias === 1) return 'Mañana'
  if (dias === -1) return 'Ayer'
  const anio = f.getFullYear() !== hoy.getFullYear() ? ` ${f.getFullYear()}` : ''
  return `${DIAS_LARGOS[f.getDay()].slice(0, 3)} ${f.getDate()} ${MESES[f.getMonth()].slice(0, 3)}${anio}`
}

export function saludo() {
  const hora = new Date().getHours()
  if (hora < 6) return 'Buenas noches'
  if (hora < 13) return 'Buenos días'
  if (hora < 21) return 'Buenas tardes'
  return 'Buenas noches'
}

/** "1.234,50" o "12,5" → "1234.50" / "12.5"; null si no es un importe. */
export function aImporte(texto: string): string | null {
  const limpio = texto
    .replace(/\s|€/g, '')
    .replace(/\.(?=\d{3}(\D|$))/g, '')
    .replace(',', '.')
  return /^\d+(\.\d{1,2})?$/.test(limpio) && Number(limpio) > 0 ? limpio : null
}

/** Un apunte en una frase, para confirmar qué se ha entendido al anotarlo. */
export function describir(a: { tipo: string; concepto: string; importe: string; pendiente: boolean }) {
  if (a.tipo === 'nota') return `Nota guardada · ${a.concepto}`
  const clase = a.tipo === 'gasto' ? 'Gasto' : a.pendiente ? 'Pendiente de cobro' : 'Cobrado'
  return `${clase} · ${a.concepto} · ${euros(a.importe)}`
}
