/**
 * Cliente de la API. El único sitio del front que sabe de HTTP.
 *
 * No calcula nada: los totales los da el backend, que es el que tiene los
 * importes en céntimos. Aquí solo se piden y se pintan.
 */
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export type Apunte = {
  id: number
  fecha: string
  // "nota" es lo dictado sin importe: se guarda con importe 0 y no suma.
  tipo: 'trabajo' | 'gasto' | 'nota'
  concepto: string
  importe: string // Decimal, llega como texto para no perder céntimos
  pendiente: boolean
  origen: string
  creado: string
  cliente_id: number | null
}

export type Resumen = {
  cobrado: string
  pendiente: string
  gastos: string
  neto: string
}

/** El token ya no vale: quien llame debe pedir uno nuevo al bot. */
export class TokenInvalido extends Error {}

/** El backend rechazó la petición con un motivo que se le puede enseñar a la gente. */
export class ErrorDeApi extends Error {}

export type Salud = {
  estado: string
  datos: { persistente: boolean; ruta: string | null; aviso: string | null }
}

/**
 * Si los datos se están guardando de verdad.
 *
 * No pide token a propósito: la alarma tiene que verse también en la
 * pantalla de entrada. Si la API no contesta devuelve null, porque entonces
 * no se sabe, y una alarma falsa enseña a no hacerle caso a las verdaderas.
 */
export async function salud(): Promise<Salud | null> {
  try {
    const respuesta = await fetch(`${BASE}/salud`)
    if (!respuesta.ok) return null
    return (await respuesta.json()) as Salud
  } catch {
    return null
  }
}

async function pedir<T>(token: string, ruta: string, opciones: RequestInit = {}): Promise<T> {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    ...opciones,
    headers: {
      ...opciones.headers,
      Authorization: `Bearer ${token}`,
    },
  })

  if (respuesta.status === 401) throw new TokenInvalido('El token no vale')
  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => null)
    throw new ErrorDeApi(cuerpo?.detail ?? `Error ${respuesta.status}`)
  }
  return respuesta.json() as Promise<T>
}

/** Para respuestas 204, que no traen cuerpo: hacer .json() de vacío revienta. */
async function pedirSinCuerpo(token: string, ruta: string, opciones: RequestInit = {}) {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    ...opciones,
    headers: { ...opciones.headers, Authorization: `Bearer ${token}` },
  })
  if (respuesta.status === 401) throw new TokenInvalido('El token no vale')
  if (!respuesta.ok) throw new ErrorDeApi(`Error ${respuesta.status}`)
}

export function listarApuntes(token: string, fecha?: string) {
  const query = fecha ? `?fecha=${fecha}` : ''
  return pedir<Apunte[]>(token, `/apuntes${query}`)
}

/** Lo que devuelve crear un apunte: el apunte y, si hay dos clientes con
 *  ese nombre, entre quiénes hay que elegir. */
export type ApunteCreado = {
  apunte: Apunte
  candidatos: Cliente[]
}

export function crearApunte(token: string, texto: string) {
  return pedir<ApunteCreado>(token, '/apuntes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto, origen: 'web' }),
  })
}

export function marcarCobrado(token: string, id: number) {
  return pedir<Apunte>(token, `/apuntes/${id}/cobrado`, { method: 'POST' })
}

export function resumenDia(token: string, fecha?: string) {
  const query = fecha ? `?fecha=${fecha}` : ''
  return pedir<Resumen>(token, `/resumen/dia${query}`)
}

export function resumenMes(token: string, anio: number, mes: number) {
  return pedir<Resumen>(token, `/resumen/mes?anio=${anio}&mes=${mes}`)
}

/**
 * El CSV no se puede enlazar con un <a href> porque la ruta exige el header
 * Authorization, así que se descarga a mano y se guarda como fichero.
 */
export async function descargarCsv(token: string, desde: string, hasta: string) {
  const respuesta = await fetch(`${BASE}/export/csv?desde=${desde}&hasta=${hasta}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (respuesta.status === 401) throw new TokenInvalido('El token no vale')
  if (!respuesta.ok) throw new ErrorDeApi(`Error ${respuesta.status}`)

  const blob = await respuesta.blob()
  const url = URL.createObjectURL(blob)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = `parte-del-dia-${desde}_${hasta}.csv`
  enlace.click()
  URL.revokeObjectURL(url)
}

// ---------- Clientes y agenda ----------

export type Cliente = {
  id: number
  nombre: string
  telefono: string | null
  direccion: string | null
  notas: string | null
}

export type ClienteListado = {
  cliente: Cliente
  debe: string
  total_trabajos: number
}

export type FichaCliente = {
  cliente: Cliente
  debe: string
  cobrado: string
  apuntes: Apunte[]
  citas: Cita[]
}

export type Cita = {
  id: number
  fecha: string
  /** Último día, incluido. Vacío = empieza y acaba el mismo día. */
  fecha_fin: string | null
  hora: string | null
  titulo: string
  direccion: string | null
  notas: string | null
  hecha: boolean
  cliente_id: number | null
  cliente: Cliente | null
}

export function listarClientes(token: string, buscar?: string) {
  const q = buscar ? `?buscar=${encodeURIComponent(buscar)}` : ''
  return pedir<ClienteListado[]>(token, `/clientes${q}`)
}

export function crearCliente(token: string, datos: Partial<Cliente> & { nombre: string }) {
  return pedir<Cliente>(token, '/clientes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

export function fichaCliente(token: string, id: number) {
  return pedir<FichaCliente>(token, `/clientes/${id}`)
}

export function editarCliente(token: string, id: number, cambios: Partial<Cliente>) {
  return pedir<Cliente>(token, `/clientes/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios),
  })
}

export async function borrarCliente(token: string, id: number) {
  await pedirSinCuerpo(token, `/clientes/${id}`, { method: 'DELETE' })
}

export function asignarCliente(token: string, apunteId: number, clienteId: number | null) {
  return pedir<Apunte>(token, `/apuntes/${apunteId}/cliente`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cliente_id: clienteId }),
  })
}

export function pendientesDeCobro(token: string) {
  return pedir<Apunte[]>(token, '/apuntes/pendientes')
}

export function citasDelDia(token: string, fecha?: string) {
  return pedir<Cita[]>(token, `/citas${fecha ? `?fecha=${fecha}` : ''}`)
}

export function citasDelMes(token: string, anio: number, mes: number) {
  return pedir<Cita[]>(token, `/citas?anio=${anio}&mes=${mes}`)
}

export function proximasCitas(token: string, limite = 10) {
  return pedir<Cita[]>(token, `/citas/proximas?limite=${limite}`)
}

export function crearCita(
  token: string,
  datos: {
    fecha: string
    titulo: string
    fecha_fin?: string | null
    hora?: string | null
    direccion?: string | null
    cliente_id?: number | null
    notas?: string | null
  },
) {
  return pedir<Cita>(token, '/citas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

export function editarCita(
  token: string,
  id: number,
  cambios: {
    titulo?: string
    fecha?: string
    fecha_fin?: string | null
    hora?: string | null
    direccion?: string | null
    notas?: string | null
    cliente_id?: number | null
  },
) {
  return pedir<Cita>(token, `/citas/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios),
  })
}

export function marcarCitaHecha(token: string, id: number, hecha = true) {
  return pedir<Cita>(token, `/citas/${id}/hecha?hecha=${hecha}`, { method: 'POST' })
}

export async function borrarCita(token: string, id: number) {
  await pedirSinCuerpo(token, `/citas/${id}`, { method: 'DELETE' })
}

export async function borrarApunte(token: string, id: number) {
  await pedirSinCuerpo(token, `/apuntes/${id}`, { method: 'DELETE' })
}

export function editarApunte(
  token: string,
  id: number,
  cambios: { concepto?: string; importe?: string; pendiente?: boolean; fecha?: string },
) {
  return pedir<Apunte>(token, `/apuntes/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios),
  })
}

export type ResumenTrimestre = {
  anio: number
  trimestre: number
  desde: string
  hasta: string
  cobrado: string
  pendiente: string
  gastos: string
  neto: string
  estimacion_130: string
}

export function resumenTrimestre(token: string) {
  return pedir<ResumenTrimestre>(token, '/resumen/trimestre')
}

// ---------- Buzón de notas ----------

/**
 * Una nota es lo apuntado que todavía no tiene ni fecha ni precio. Por
 * debajo es un apunte de tipo "nota", el mismo que crea el bot cuando se le
 * dicta algo sin importe: es la misma fila, no una copia.
 */
export type Nota = {
  id: number
  fecha: string // el día en que se apuntó, no el día en que toca
  concepto: string
  hecha: boolean
  origen: string
  creado: string
  cliente_id: number | null
  cliente: Cliente | null
}

/** Por defecto, lo que queda por hacer; con `hechas`, las ya cumplidas. */
export function listarNotas(token: string, hechas = false) {
  return pedir<Nota[]>(token, `/notas${hechas ? '?hechas=true' : ''}`)
}

export function marcarNotaHecha(token: string, id: number, hecha = true) {
  return pedir<Nota>(token, `/notas/${id}/hecha?hecha=${hecha}`, { method: 'POST' })
}

export function crearNota(token: string, texto: string) {
  return pedir<Nota>(token, '/notas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto }),
  })
}

export function editarNota(token: string, id: number, texto: string) {
  return pedir<Nota>(token, `/notas/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto }),
  })
}

export async function borrarNota(token: string, id: number) {
  await pedirSinCuerpo(token, `/notas/${id}`, { method: 'DELETE' })
}

/** Le pone fecha: devuelve la cita nueva y la nota deja de existir. */
export function agendarNota(
  token: string,
  id: number,
  datos: { fecha: string; fecha_fin?: string | null; hora?: string | null; titulo?: string },
) {
  return pedir<Cita>(token, `/notas/${id}/agendar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

// ---------- Hábitos ----------

/**
 * El estado de cada día lo calcula el backend, el mismo para la semana de la
 * lista que para el calendario del detalle. Aquí solo se pinta.
 */
export type EstadoDia = 'hecho' | 'hoy' | 'fallado' | 'futuro' | 'no_toca' | 'antes'

export type Habito = {
  id: number
  nombre: string
  dias: number[] // 0 es lunes
  inicio: string
  recordar_a: string | null // "HH:MM:SS"
}

export type DiaHabito = { fecha: string; estado: EstadoDia }

export type ResumenHabito = {
  habito: Habito
  semana: DiaHabito[]
  racha: number
  toca_hoy: boolean
  hecho_hoy: boolean
}

export type DetalleHabito = {
  habito: Habito
  racha: number
  mejor_racha: number
  cumplidos: number
  programados: number
  porcentaje: number
  anio: number
  mes: number
  dias_del_mes: DiaHabito[]
}

export type DatosHabito = { nombre: string; dias: number[]; recordar_a: string | null }

export function listarHabitos(token: string) {
  return pedir<ResumenHabito[]>(token, '/habitos')
}

export function crearHabito(token: string, datos: DatosHabito) {
  return pedir<ResumenHabito>(token, '/habitos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

export function editarHabito(token: string, id: number, cambios: Partial<DatosHabito>) {
  return pedir<ResumenHabito>(token, `/habitos/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios),
  })
}

export async function borrarHabito(token: string, id: number) {
  await pedirSinCuerpo(token, `/habitos/${id}`, { method: 'DELETE' })
}

export function marcarDiaHabito(token: string, id: number, fecha: string, hecho: boolean) {
  return pedir<ResumenHabito>(token, `/habitos/${id}/dias`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fecha, hecho }),
  })
}

export function detalleHabito(token: string, id: number, anio: number, mes: number) {
  return pedir<DetalleHabito>(token, `/habitos/${id}?anio=${anio}&mes=${mes}`)
}
