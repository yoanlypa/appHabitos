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
  // La foto del ticket, si el gasto salió de escanearlo.
  factura_id: number | null
  // Si esa factura la emitió Yoa (cuelga de un trabajo) y no es de compra.
  factura_emitida: boolean
  // De qué trabajo es este gasto (otro apunte), y cómo se llama.
  trabajo_id: number | null
  trabajo_titulo: string | null
  // Solo trabajos: si lo factura Yoa. Solo gastos sueltos: marcado a mano.
  para_gestoria: boolean
  // Lo que cuenta: si sale en lo que se manda a la gestoría. Lo decide el
  // backend; aquí solo se pinta.
  gestoria: boolean
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

/** Trabajos y gastos entre dos fechas (incluidas), el más reciente primero. */
export function movimientos(token: string, desde: string, hasta: string) {
  return pedir<Apunte[]>(token, `/apuntes/rango?desde=${desde}&hasta=${hasta}`)
}

export function marcarCobrado(token: string, id: number) {
  return pedir<Apunte>(token, `/apuntes/${id}/cobrado`, { method: 'POST' })
}

export function resumenDia(token: string, fecha?: string) {
  const query = fecha ? `?fecha=${fecha}` : ''
  return pedir<Resumen>(token, `/resumen/dia${query}`)
}

/** Totales entre dos fechas incluidas (año, mes pasado, personalizado...). */
export function resumenRango(token: string, desde: string, hasta: string) {
  return pedir<Resumen>(token, `/resumen/rango?desde=${desde}&hasta=${hasta}`)
}

export type ResumenDeMes = Resumen & { mes: number }

/** Los doce meses de un año, para el gráfico de Finanzas. */
export function resumenMeses(token: string, anio: number) {
  return pedir<ResumenDeMes[]>(token, `/resumen/meses?anio=${anio}`)
}

export function resumenMes(token: string, anio: number, mes: number) {
  return pedir<Resumen>(token, `/resumen/mes?anio=${anio}&mes=${mes}`)
}

/**
 * Un CSV no se puede enlazar con un <a href> porque la ruta exige el header
 * Authorization, así que se descarga a mano y se guarda como fichero.
 */
async function descargar(token: string, ruta: string, nombre: string): Promise<boolean> {
  const respuesta = await fetch(`${BASE}${ruta}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (respuesta.status === 401) throw new TokenInvalido('El token no vale')
  if (!respuesta.ok) throw new ErrorDeApi(`Error ${respuesta.status}`)
  // 204: no había nada que descargar.
  if (respuesta.status === 204) return false

  const blob = await respuesta.blob()
  const url = URL.createObjectURL(blob)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = nombre
  enlace.click()
  URL.revokeObjectURL(url)
  return true
}

/**
 * La copia de seguridad completa, la misma que manda el bot cada domingo:
 * un ZIP que se le reenvía al bot para restaurar. Devuelve false si aún no
 * hay nada que guardar.
 */
export function descargarCopia(token: string) {
  const hoy = new Date().toISOString().slice(0, 10)
  return descargar(token, '/export/copia', `parte-del-dia-${hoy}.zip`)
}

/** Todos los movimientos del periodo. */
export function descargarCsv(token: string, desde: string, hasta: string) {
  return descargar(
    token,
    `/export/csv?desde=${desde}&hasta=${hasta}`,
    `parte-del-dia-${desde}_${hasta}.csv`,
  )
}

/** Solo lo que va a la gestoría: facturas emitidas y sus gastos. */
export function descargarCsvGestoria(token: string, desde: string, hasta: string) {
  return descargar(
    token,
    `/gestoria/csv?desde=${desde}&hasta=${hasta}`,
    `gestoria-${desde}_${hasta}.csv`,
  )
}

// ---------- Importar varios movimientos ----------

/** Un movimiento leído de una lista, un CSV, un Excel o una captura. */
export type MovimientoImportado = {
  fecha: string
  // null: la tabla no decía si entra o sale. Se pregunta, nunca se supone.
  tipo: 'trabajo' | 'gasto' | null
  concepto: string
  importe: string
  pendiente: boolean
  // Mismo día, tipo e importe que algo que ya está. Se enseña y se puede meter igual.
  repetido: boolean
}

export type LecturaImportacion = { movimientos: MovimientoImportado[]; falta_tipo: boolean }

/** Lee un fichero (CSV, Excel, captura) o un texto pegado. No guarda nada. */
export function leerImportacion(token: string, entrada: { fichero?: File; texto?: string }) {
  const datos = new FormData()
  if (entrada.fichero) datos.append('fichero', entrada.fichero)
  if (entrada.texto) datos.append('texto', entrada.texto)
  return pedir<LecturaImportacion>(token, '/importar/leer', { method: 'POST', body: datos })
}

/** Los mismos movimientos con el tipo elegido para los que no lo traían. */
export function revisarImportacion(token: string, movimientos: MovimientoImportado[], tipo: 'trabajo' | 'gasto') {
  return pedir<LecturaImportacion>(token, '/importar/revisar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ movimientos, tipo }),
  })
}

/** Mete los elegidos. Con `todo`, entran tal cual aunque parezcan repetidos. */
export function confirmarImportacion(token: string, movimientos: MovimientoImportado[], todo: boolean) {
  return pedir<{ apuntes: Apunte[]; ya_estaban: number }>(token, '/importar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ movimientos, todo }),
  })
}

/** Quita lo recién importado (lo que no se haya tocado desde entonces). */
export function deshacerImportacion(token: string, ids: number[]) {
  return pedir<{ borrados: number }>(token, '/importar/deshacer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
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
  trabajo_id: number | null
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
    trabajo_id?: number | null
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
    trabajo_id?: number | null
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

export type DatosMovimiento = {
  tipo: 'trabajo' | 'gasto'
  concepto: string
  importe: string
  fecha: string
  pendiente: boolean
  /** El trabajo (obra) al que pertenece, si es de uno. */
  trabajo_id: number | null
  /** Solo si es suelto (sin trabajo): va a la gestoría. */
  para_gestoria: boolean
}

/** Lo de un periodo repartido en lo que va a la gestoría y lo que no. */
export type ParteGestoria = {
  emitidas: Apunte[]
  recibidas: Apunte[]
  trabajos_fuera: Apunte[]
  gastos_fuera: Apunte[]
  facturado: string
  gastos: string
  diferencia: string
  /** Cuántos de los que van no tienen su factura o ticket colgado. */
  sin_documento: number
}

export function parteGestoria(token: string, desde: string, hasta: string) {
  return pedir<ParteGestoria>(token, `/gestoria?desde=${desde}&hasta=${hasta}`)
}

/** Un trabajo o gasto desde el formulario de Finanzas, con su fecha. */
export function crearMovimiento(token: string, datos: DatosMovimiento) {
  return pedir<Apunte>(token, '/apuntes/movimiento', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

export async function borrarApunte(token: string, id: number) {
  await pedirSinCuerpo(token, `/apuntes/${id}`, { method: 'DELETE' })
}

export function editarApunte(
  token: string,
  id: number,
  cambios: {
    concepto?: string
    importe?: string
    pendiente?: boolean
    fecha?: string
    tipo?: 'trabajo' | 'gasto'
    trabajo_id?: number | null
    para_gestoria?: boolean
  },
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
  trabajo_id: number | null
}

/** Por defecto, lo que queda por hacer; con `hechas`, las ya cumplidas. */
export function listarNotas(token: string, hechas = false) {
  return pedir<Nota[]>(token, `/notas${hechas ? '?hechas=true' : ''}`)
}

export function marcarNotaHecha(token: string, id: number, hecha = true) {
  return pedir<Nota>(token, `/notas/${id}/hecha?hecha=${hecha}`, { method: 'POST' })
}

/** Con `trabajoId`, la nota es de ese trabajo (y de su cliente). */
export function crearNota(token: string, texto: string, trabajoId?: number) {
  return pedir<Nota>(token, '/notas', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texto, trabajo_id: trabajoId ?? null }),
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

/* ---------- Escáner de tickets ---------- */

/** Lo que se leyó en la foto. Cualquier campo puede venir vacío: un hueco
 *  se ve, un número inventado se cuela. */
export type TicketLeido = {
  factura_id: number
  total: string | null
  fecha: string | null
  comercio: string | null
  iva: string | null
  concepto: string
  /** Si la factura la emite Yoa: va a un trabajo, no a un gasto. */
  emitida: boolean
  cliente: string | null
  a_cobrar: string | null
  candidatos: Apunte[]
}

/** Una factura de Yoa confirmada: a un trabajo ya anotado o a uno nuevo. */
export function confirmarFacturaEmitida(
  token: string,
  facturaId: number,
  datos: { apunte_id: number | null; cobrada: boolean; concepto: string; importe: string; fecha: string | null },
) {
  return pedir<Apunte>(token, `/facturas/${facturaId}/emitida`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

/** Sube la foto y la lee. No anota nada: eso es `confirmarGastoDeFactura`. */
export function escanearFactura(token: string, imagen: Blob) {
  const datos = new FormData()
  datos.append('imagen', imagen, imagen.type === 'application/pdf' ? 'factura.pdf' : 'ticket.jpg')
  // Sin Content-Type a mano: el navegador pone el multipart con su boundary.
  return pedir<TicketLeido>(token, '/facturas/escanear', { method: 'POST', body: datos })
}

export function confirmarGastoDeFactura(
  token: string,
  facturaId: number,
  gasto: {
    concepto: string
    importe: string
    fecha: string | null
    trabajo_id?: number | null
    para_gestoria?: boolean
  },
) {
  return pedir<Apunte>(token, `/facturas/${facturaId}/gasto`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(gasto),
  })
}

/** Abre un PDF que pide token: se baja con fetch y se abre como blob. */
async function abrirPdf(token: string, ruta: string, nombre: string) {
  // La pestaña se abre antes de esperar a la red: Safari en iPhone bloquea
  // window.open si no ocurre justo al tocar el botón.
  const ventana = window.open('', '_blank')
  const respuesta = await fetch(`${BASE}${ruta}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (respuesta.status === 401) {
    ventana?.close()
    throw new TokenInvalido('El token no vale')
  }
  if (!respuesta.ok) {
    ventana?.close()
    const cuerpo = await respuesta.json().catch(() => null)
    throw new ErrorDeApi(cuerpo?.detail ?? 'No se ha podido abrir el PDF')
  }
  const url = URL.createObjectURL(await respuesta.blob())
  if (ventana) {
    ventana.location.href = url
  } else {
    const enlace = document.createElement('a')
    enlace.href = url
    enlace.download = nombre
    enlace.click()
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** El ticket escaneado en PDF, blanco y negro, como CamScanner. */
export function abrirFactura(token: string, facturaId: number) {
  return abrirPdf(token, `/facturas/${facturaId}/pdf`, `ticket-${facturaId}.pdf`)
}

/** Todos los tickets del periodo en un PDF, uno por página, para la gestoría. */
export function abrirFacturasDelPeriodo(
  token: string,
  desde: string,
  hasta: string,
  emitidas = false,
  /** Solo las que van a la gestoría. */
  gestoria = false,
) {
  return abrirPdf(
    token,
    `/facturas/pdf?desde=${desde}&hasta=${hasta}&emitidas=${emitidas}&gestoria=${gestoria}`,
    `${emitidas ? 'facturas-emitidas' : gestoria ? 'facturas-recibidas' : 'tickets'}-${desde}_${hasta}.pdf`,
  )
}

// ---------- Ajustes ----------

export type Ajustes = {
  avisos_activos: boolean
  /** A dónde se mandan también por correo los avisos de citas. */
  correo: string | null
  /** Si el servidor sabe mandar correos (falta la clave de Resend si no). */
  correo_disponible: boolean
  /** Con cuántos minutos de antelación se avisa de una cita ese mismo día. */
  aviso_cita_minutos: number
}

export function leerAjustes(token: string) {
  return pedir<Ajustes>(token, '/ajustes')
}

/** null o vacío quita el correo. */
export function guardarCorreo(token: string, correo: string | null) {
  return pedir<Ajustes>(token, '/ajustes', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ correo }),
  })
}

export function probarCorreo(token: string) {
  return pedir<{ enviado_a: string }>(token, '/ajustes/correo/prueba', { method: 'POST' })
}

// ---------- Trabajos (obras) ----------

/** Una obra: la ficha que junta cobros, gastos, notas y citas de un trabajo. */
export type Trabajo = {
  id: number
  titulo: string
  descripcion: string | null
  cliente_id: number | null
  cliente: Cliente | null
  fecha_inicio: string | null
  fecha_fin: string | null
  /** Lo factura Yoa: sus cobros y gastos van a la gestoría. */
  facturado: boolean
  /** El cliente dejó reseña. */
  resena: boolean
}

/** Las cuentas de un trabajo. Las hace el backend. */
export type Cuentas = {
  cobrado: string
  pendiente: string
  gastos: string
  ingresos: string
  beneficio: string
}

export type TrabajoListado = {
  trabajo: Trabajo
  cuentas: Cuentas
  notas_pendientes: number
  proxima_cita: Cita | null
}

export type FichaDeTrabajo = {
  trabajo: Trabajo
  cuentas: Cuentas
  movimientos: Apunte[]
  notas: Nota[]
  citas: Cita[]
}

export type DatosTrabajo = {
  titulo: string
  cliente_id: number | null
  fecha_inicio: string | null
  fecha_fin: string | null
  facturado: boolean
  resena: boolean
  descripcion: string | null
}

export function listarTrabajos(token: string) {
  return pedir<TrabajoListado[]>(token, '/trabajos')
}

export function fichaDeTrabajo(token: string, id: number) {
  return pedir<FichaDeTrabajo>(token, `/trabajos/${id}`)
}

export function crearTrabajo(token: string, datos: Partial<DatosTrabajo> & { titulo: string }) {
  return pedir<Trabajo>(token, '/trabajos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  })
}

/** Solo cambia lo que se manda; null en cliente o fechas lo vacía. */
export function editarTrabajo(token: string, id: number, cambios: Partial<DatosTrabajo>) {
  return pedir<Trabajo>(token, `/trabajos/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cambios),
  })
}

/** Borra la ficha; lo que tenía dentro se queda, suelto. */
export async function borrarTrabajo(token: string, id: number) {
  await pedirSinCuerpo(token, `/trabajos/${id}`, { method: 'DELETE' })
}

/** Mete varios cobros o gastos en un trabajo de una vez (null: los saca). */
export function asignarTrabajo(token: string, apunteIds: number[], trabajoId: number | null) {
  return pedir<Apunte[]>(token, '/apuntes/trabajo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ apunte_ids: apunteIds, trabajo_id: trabajoId }),
  })
}

// --- Casa ---------------------------------------------------------------------

export type Miembro = { id: number; user_id: number; nombre: string; titular: boolean; efectivo: boolean }

export type MiCasa = {
  hogar_id: number
  nombre: string
  yo: Miembro
  miembros: Miembro[]
  /** Quien no es titular solo ve Casa: el negocio no es cosa suya. */
  solo_casa: boolean
  categorias: string[]
  hay_recetas: boolean
}

export type GastoCasa = {
  id: number
  user_id: number
  fecha: string
  concepto: string
  importe: string
  categoria: string
  origen: string
  efectivo: boolean
}

export type ResumenCasa = {
  total: string
  anterior: string
  efectivo: string
  sin_detallar: string
  por_categoria: { nombre: string; total: string }[]
  por_persona: { nombre: string; total: string }[]
}

export type Articulo = { id: number; texto: string; hay: boolean; anadido_por: number | null }

export type Receta = {
  nombre: string
  minutos: number | null
  usa: string[]
  falta: string[]
  pasos: string[]
}

export type DatosGastoCasa = {
  concepto: string
  importe: string
  fecha: string
  categoria: string
  pagado_por: number
  efectivo: boolean
}

/** Lo que debería haber en la cartera de alguien desde que la contó. */
export type Cartera = {
  user_id: number
  nombre: string
  esperado: string | null
  contado_el: string | null
  entradas: string
  gastado: string
}

export type Recuento = { esperado: string | null; contado: string; sin_detallar: string; sobra: string }

const JSON_CAB = { 'Content-Type': 'application/json' }

export function miCasa(token: string) {
  return pedir<MiCasa>(token, '/casa')
}

export function cambiarMiNombre(token: string, nombre: string) {
  return pedir<Miembro>(token, '/casa/yo', { method: 'PATCH', headers: JSON_CAB, body: JSON.stringify({ nombre }) })
}

export function cambiarPagoHabitual(token: string, efectivo: boolean) {
  return pedir<Miembro>(token, '/casa/yo', { method: 'PATCH', headers: JSON_CAB, body: JSON.stringify({ efectivo }) })
}

export function carteras(token: string) {
  return pedir<Cartera[]>(token, '/casa/carteras')
}

export function meterEnCartera(token: string, importe: string) {
  return pedir<{ id: number }>(token, '/casa/cartera/entrada', { method: 'POST', headers: JSON_CAB, body: JSON.stringify({ importe }) })
}

export function contarCartera(token: string, importe: string) {
  return pedir<Recuento>(token, '/casa/cartera/recuento', { method: 'POST', headers: JSON_CAB, body: JSON.stringify({ importe }) })
}

export function crearInvitacion(token: string) {
  return pedir<{ codigo: string; dias: number }>(token, '/casa/invitacion', { method: 'POST' })
}

export function quitarMiembro(token: string, id: number) {
  return pedirSinCuerpo(token, `/casa/miembros/${id}`, { method: 'DELETE' })
}

/** Sin token: quien llega con el enlace todavía no tiene. */
/** Lo que enseña el enlace de invitación antes de entrar. `volver`: quienes
 *  entraron solo por la web y pueden volver a ser ellos (sin duplicarse). */
export type InvitacionVista = {
  casa: string
  miembros: string[]
  volver: { id: number; nombre: string }[]
}

export async function verInvitacion(codigo: string): Promise<InvitacionVista> {
  const r = await fetch(`${BASE}/casa/invitacion/${encodeURIComponent(codigo)}`)
  const cuerpo = await r.json().catch(() => null)
  if (!r.ok) throw new ErrorDeApi(cuerpo?.detail ?? `Error ${r.status}`)
  return cuerpo
}

export async function unirseACasa(codigo: string, nombre: string, miembroId?: number): Promise<string> {
  const r = await fetch(`${BASE}/casa/unirse`, {
    method: 'POST',
    headers: JSON_CAB,
    body: JSON.stringify({ codigo, nombre, miembro_id: miembroId ?? null }),
  })
  const cuerpo = await r.json().catch(() => null)
  if (!r.ok) throw new ErrorDeApi(cuerpo?.detail ?? `Error ${r.status}`)
  return cuerpo.token as string
}

export function gastosCasa(token: string, desde: string, hasta: string) {
  return pedir<GastoCasa[]>(token, `/casa/gastos?desde=${desde}&hasta=${hasta}`)
}

export function resumenCasa(token: string, desde: string, hasta: string) {
  return pedir<ResumenCasa>(token, `/casa/resumen?desde=${desde}&hasta=${hasta}`)
}

export function anotarGastoCasa(token: string, texto: string) {
  return pedir<GastoCasa>(token, '/casa/gastos/texto', { method: 'POST', headers: JSON_CAB, body: JSON.stringify({ texto }) })
}

export function crearGastoCasa(token: string, datos: DatosGastoCasa) {
  return pedir<GastoCasa>(token, '/casa/gastos', { method: 'POST', headers: JSON_CAB, body: JSON.stringify(datos) })
}

export function editarGastoCasa(token: string, id: number, cambios: Partial<DatosGastoCasa>) {
  return pedir<GastoCasa>(token, `/casa/gastos/${id}`, { method: 'PATCH', headers: JSON_CAB, body: JSON.stringify(cambios) })
}

export function borrarGastoCasa(token: string, id: number) {
  return pedirSinCuerpo(token, `/casa/gastos/${id}`, { method: 'DELETE' })
}

export function listaCompra(token: string) {
  return pedir<Articulo[]>(token, '/casa/lista')
}

export function anadirALista(token: string, texto: string) {
  return pedir<Articulo[]>(token, '/casa/lista', { method: 'POST', headers: JSON_CAB, body: JSON.stringify({ texto }) })
}

export function cambiarArticulo(token: string, id: number, cambios: { hay?: boolean; texto?: string }) {
  return pedir<Articulo>(token, `/casa/lista/${id}`, { method: 'PATCH', headers: JSON_CAB, body: JSON.stringify(cambios) })
}

export function borrarArticulo(token: string, id: number) {
  return pedirSinCuerpo(token, `/casa/lista/${id}`, { method: 'DELETE' })
}

export function pedirRecetas(token: string, preferencias: string) {
  return pedir<Receta[]>(token, '/casa/recetas', { method: 'POST', headers: JSON_CAB, body: JSON.stringify({ preferencias }) })
}
