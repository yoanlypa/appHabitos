/**
 * La pantalla de trabajo: resumen, alta de apuntes y lista del día.
 *
 * El alta usa la misma sintaxis que el bot a propósito — quien apunta desde
 * el móvil por Telegram no tiene que aprender otra forma de escribir aquí.
 *
 * Los datos se recargan subiendo `recargas`: así el efecto de carga es el
 * único sitio que pide a la API, y las acciones solo dicen "algo cambió".
 */
import { useEffect, useState } from 'react'
import {
  asignarCliente,
  borrarApunte,
  crearApunte,
  descargarCsv,
  listarApuntes,
  marcarCobrado,
  resumenDia,
  resumenMes,
  resumenTrimestre,
  TokenInvalido,
  type Apunte,
  type ApunteCreado,
  type Resumen,
  type ResumenTrimestre,
} from '../api'
import { euros as importe, iso } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
  /** La cabecera y el botón de salir los pone App; aquí sobran. */
  conCabecera?: boolean
}

export function Panel({ token, onTokenInvalido, conCabecera = true }: Props) {
  const [apuntes, setApuntes] = useState<Apunte[]>([])
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [periodo, setPeriodo] = useState<'dia' | 'mes' | 'trimestre'>('dia')
  const [trimestre, setTrimestre] = useState<ResumenTrimestre | null>(null)
  const [recargas, setRecargas] = useState(0)
  const [texto, setTexto] = useState('')
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(true)
  const [duda, setDuda] = useState<ApunteCreado | null>(null)

  useEffect(() => {
    let cancelado = false

    async function cargar() {
      const hoy = new Date()
      try {
        const [lista, totales, tri] = await Promise.all([
          listarApuntes(token),
          periodo === 'mes'
            ? resumenMes(token, hoy.getFullYear(), hoy.getMonth() + 1)
            : resumenDia(token),
          periodo === 'trimestre' ? resumenTrimestre(token) : Promise.resolve(null),
        ])
        if (cancelado) return
        setApuntes(lista)
        setResumen(totales)
        setTrimestre(tri)
        setError('')
      } catch (e) {
        if (cancelado) return
        if (e instanceof TokenInvalido) return onTokenInvalido()
        setError(e instanceof Error ? e.message : 'No se han podido cargar los apuntes')
      } finally {
        if (!cancelado) setCargando(false)
      }
    }

    void cargar()
    return () => {
      cancelado = true
    }
  }, [token, periodo, recargas, onTokenInvalido])

  /** Ejecuta una acción y recarga; si el token cayó, devuelve a la entrada. */
  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      if (e instanceof TokenInvalido) return onTokenInvalido()
      setError(e instanceof Error ? e.message : 'Algo ha fallado')
    }
  }

  async function anotar(e: React.FormEvent) {
    e.preventDefault()
    const limpio = texto.trim()
    if (!limpio) return
    await accion(async () => {
      const creado = await crearApunte(token, limpio)
      setTexto('')
      // Dos clientes con ese nombre: preguntamos en vez de adivinar, igual
      // que hace el bot. Colgarlo de la Ana equivocada sería peor.
      setDuda(creado.candidatos.length > 1 ? creado : null)
    })
  }

  async function resolverDuda(clienteId: number | null) {
    if (!duda) return
    const apunteId = duda.apunte.id
    setDuda(null)
    await accion(() => asignarCliente(token, apunteId, clienteId))
  }

  function descargarElMes() {
    const hoy = new Date()
    const primero = new Date(hoy.getFullYear(), hoy.getMonth(), 1)
    void accion(() => descargarCsv(token, iso(primero), iso(hoy)))
  }

  return (
    <>
      {conCabecera && (
        <header>
          <h1>Parte del día</h1>
        </header>
      )}

      <section className="totales">
        <div className="pestanas">
          <button
            className={periodo === 'dia' ? 'activa' : ''}
            onClick={() => setPeriodo('dia')}
          >
            Hoy
          </button>
          <button
            className={periodo === 'mes' ? 'activa' : ''}
            onClick={() => setPeriodo('mes')}
          >
            Este mes
          </button>
          <button
            className={periodo === 'trimestre' ? 'activa' : ''}
            onClick={() => setPeriodo('trimestre')}
          >
            Trimestre
          </button>
        </div>

        {periodo === 'trimestre' && trimestre && (
          <>
            <dl>
              <div>
                <dt>Cobrado</dt>
                <dd className="cobrado">{importe(trimestre.cobrado)}</dd>
              </div>
              <div>
                <dt>Gastos</dt>
                <dd className="gasto">{importe(trimestre.gastos)}</dd>
              </div>
              <div className="neto">
                <dt>
                  Neto del {trimestre.trimestre}º trimestre
                </dt>
                <dd>{importe(trimestre.neto)}</dd>
              </div>
            </dl>
            <p className="ayuda nota-130">
              Modelo 130 aproximado: <strong>{importe(trimestre.estimacion_130)}</strong>.
              Es el 20% del neto, para hacerte una idea; confírmalo con tu gestor.
            </p>
          </>
        )}

        {periodo !== 'trimestre' && resumen && (
          <dl>
            <div>
              <dt>Cobrado</dt>
              <dd className="cobrado">{importe(resumen.cobrado)}</dd>
            </div>
            <div>
              <dt>Pendiente</dt>
              <dd className="pendiente">{importe(resumen.pendiente)}</dd>
            </div>
            <div>
              <dt>Gastos</dt>
              <dd className="gasto">{importe(resumen.gastos)}</dd>
            </div>
            <div className="neto">
              <dt>Neto</dt>
              <dd>{importe(resumen.neto)}</dd>
            </div>
          </dl>
        )}
      </section>

      <form className="alta" onSubmit={anotar}>
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Cambio de grifo Ana 120"
          aria-label="Nuevo apunte"
        />
        <button type="submit" disabled={!texto.trim()}>
          Anotar
        </button>
      </form>
      <p className="ayuda">
        <code>Cambio de grifo Ana 120</code> cobrado ·{' '}
        <code>pendiente Reforma baño 980</code> sin cobrar · <code>-45 gasolina</code> gasto
      </p>

      {duda && (
        <div className="duda">
          <p>
            ¿Qué <strong>{duda.candidatos[0].nombre.split(' ')[0]}</strong> es
            «{duda.apunte.concepto}»?
          </p>
          <div className="opciones">
            {duda.candidatos.map((c) => (
              <button key={c.id} onClick={() => void resolverDuda(c.id)}>
                {c.nombre}
                {c.telefono || c.direccion ? ` · ${c.telefono ?? c.direccion}` : ''}
              </button>
            ))}
            <button className="enlace" onClick={() => void resolverDuda(null)}>
              Ninguna
            </button>
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <section className="apuntes">
        <h2>Hoy</h2>
        {cargando ? (
          <p className="vacio">Cargando…</p>
        ) : apuntes.length === 0 ? (
          <p className="vacio">Aún no has anotado nada hoy.</p>
        ) : (
          <ul>
            {apuntes.map((a) => (
              <li key={a.id} className={a.tipo}>
                <span className="concepto">{a.concepto}</span>
                <span className={`importe ${a.tipo}`}>
                  {a.tipo === 'gasto' ? '−' : ''}
                  {importe(a.importe)}
                </span>
                {a.pendiente ? (
                  <button
                    className="cobrar"
                    onClick={() => void accion(() => marcarCobrado(token, a.id))}
                  >
                    Cobrar
                  </button>
                ) : (
                  <span className="etiqueta">{a.tipo === 'gasto' ? 'gasto' : 'cobrado'}</span>
                )}
                <button
                  className="mini borrar"
                  title="Borrar este apunte"
                  onClick={() => {
                    if (confirm(`¿Borrar «${a.concepto}»?`)) {
                      void accion(() => borrarApunte(token, a.id))
                    }
                  }}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer>
        <button className="enlace" onClick={descargarElMes}>
          Descargar el mes en CSV
        </button>
      </footer>
    </>
  )
}
