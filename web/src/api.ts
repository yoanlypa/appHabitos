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
  tipo: 'trabajo' | 'gasto'
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

export function crearApunte(token: string, texto: string) {
  return pedir<Apunte>(token, '/apuntes', {
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

export function marcarCitaHecha(token: string, id: number, hecha = true) {
  return pedir<Cita>(token, `/citas/${id}/hecha?hecha=${hecha}`, { method: 'POST' })
}

export async function borrarCita(token: string, id: number) {
  await pedirSinCuerpo(token, `/citas/${id}`, { method: 'DELETE' })
}
