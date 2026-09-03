/**
 * Lo que te deben, de lo más viejo a lo más reciente.
 *
 * Se muestra la antigüedad ("hace 3 semanas") en vez de solo la fecha:
 * saber que algo lleva dos meses sin cobrarse es lo que hace que cojas el
 * teléfono, y una fecha suelta no transmite eso.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  asignarCliente,
  listarClientes,
  marcarCobrado,
  pendientesDeCobro,
  TokenInvalido,
  type Apunte,
  type ClienteListado,
} from '../api'
import { antiguedad, euros } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

export function Cobros({ token, onTokenInvalido }: Props) {
  const [pendientes, setPendientes] = useState<Apunte[]>([])
  const [clientes, setClientes] = useState<ClienteListado[]>([])
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(true)

  const fallo = useCallback(
    (e: unknown) => {
      if (e instanceof TokenInvalido) return onTokenInvalido()
      setError(e instanceof Error ? e.message : 'Algo ha fallado')
    },
    [onTokenInvalido],
  )

  useEffect(() => {
    let cancelado = false
    async function cargar() {
      try {
        const [p, c] = await Promise.all([pendientesDeCobro(token), listarClientes(token)])
        if (cancelado) return
        setPendientes(p)
        setClientes(c)
        setError('')
      } catch (e) {
        if (!cancelado) fallo(e)
      } finally {
        if (!cancelado) setCargando(false)
      }
    }
    void cargar()
    return () => {
      cancelado = true
    }
  }, [token, recargas, fallo])

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      fallo(e)
    }
  }

  const total = pendientes.reduce((suma, a) => suma + Number(a.importe), 0)

  return (
    <section className="apuntes">
      <div className="totales">
        <dl>
          <div className="neto">
            <dt>Te deben en total</dt>
            <dd className={total > 0 ? 'pendiente' : ''}>{euros(total)}</dd>
          </div>
        </dl>
      </div>

      {error && <p className="error">{error}</p>}

      <h2>Sin cobrar</h2>
      {cargando ? (
        <p className="vacio">Cargando…</p>
      ) : pendientes.length === 0 ? (
        <p className="vacio">No te debe nadie. Bien.</p>
      ) : (
        <ul>
          {pendientes.map((a) => (
            <li key={a.id} className="trabajo pendiente-fila">
              <span className="concepto">
                {a.concepto}
                <small>{antiguedad(a.fecha)}</small>
              </span>
              <span className="importe pendiente">{euros(a.importe)}</span>
              <select
                aria-label="Cliente"
                className="mini-select"
                value={a.cliente_id ?? ''}
                onChange={(e) =>
                  void accion(() =>
                    asignarCliente(token, a.id, e.target.value ? Number(e.target.value) : null),
                  )
                }
              >
                <option value="">Sin cliente</option>
                {clientes.map((c) => (
                  <option key={c.cliente.id} value={c.cliente.id}>
                    {c.cliente.nombre}
                  </option>
                ))}
              </select>
              <button className="cobrar" onClick={() => void accion(() => marcarCobrado(token, a.id))}>
                Cobrar
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
