/** Las pantallas de la app, en el orden en que salen en el menú. */
export const SECCIONES = [
  { id: 'inicio', nombre: 'Inicio' },
  { id: 'notas', nombre: 'Notas' },
  { id: 'agenda', nombre: 'Agenda' },
  { id: 'finanzas', nombre: 'Finanzas' },
  { id: 'habitos', nombre: 'Hábitos' },
  { id: 'clientes', nombre: 'Clientes' },
] as const

export type Seccion = (typeof SECCIONES)[number]['id']

/** Para saltar de una pantalla a otra; a la agenda se le puede decir el día. */
export type Ir = (destino: Seccion, dia?: string) => void
