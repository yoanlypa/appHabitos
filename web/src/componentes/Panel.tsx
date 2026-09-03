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
  crearApunte,
  descargarCsv,
  listarApuntes,
  marcarCobrado,
  resumenDia,
  resumenMes,
  TokenInvalido,
  type Apunte,
  type Resumen,
} from '../api'

const euros = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' })

function importe(valor: string) {
  return euros.format(Number(valor))
}

/** "sv-SE" da el formato YYYY-MM-DD, que es el que espera la API. */
function iso(fecha: Date) {
  return fecha.toLocaleDateString('sv-SE')
}

type Props = {
  token: string
  onSalir: () => void
  onTokenInvalido: () => void
}

export function Panel({ token, onSalir, onTokenInvalido }: Props) {
  const [apuntes, setApuntes] = useState<Apunte[]>([])
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [periodo, setPeriodo] = useState<'dia' | 'mes'>('dia')
  const [recargas, setRecargas] = useState(0)
  const [texto, setTexto] = useState('')
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    let cancelado = false

    async function cargar() {
      const hoy = new Date()
      try {
        const [lista, totales] = await Promise.all([
          listarApuntes(token),
          periodo === 'dia'
            ? resumenDia(token)
            : resumenMes(token, hoy.getFullYear(), hoy.getMonth() + 1),
        ])
        if (cancelado) return
        setApuntes(lista)
        setResumen(totales)
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
      await crearApunte(token, limpio)
      setTexto('')
    })
  }

  function descargarElMes() {
    const hoy = new Date()
    const primero = new Date(hoy.getFullYear(), hoy.getMonth(), 1)
    void accion(() => descargarCsv(token, iso(primero), iso(hoy)))
  }

  return (
    <main className="panel">
      <header>
        <h1>Parte del día</h1>
        <button className="enlace" onClick={onSalir}>
          Salir
        </button>
      </header>

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
        </div>

        {resumen && (
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
    </main>
  )
}
