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
