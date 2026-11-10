/**
 * Lo que te deben, de lo más viejo a lo más reciente.
 *
 * Se muestra la antigüedad ("hace 3 semanas") en vez de solo la fecha:
 * saber que algo lleva dos meses sin cobrarse es lo que hace que cojas el
 * teléfono, y una fecha suelta no transmite eso.
 */
import { PartyPopper } from 'lucide-react'
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
import { avisar } from '../ui/avisos'
import { ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { antiguedad, euros } from '../utiles'
import { FilaMovimiento } from './FilaMovimiento'

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

  // En céntimos enteros: sumar euros con decimales acaba en 0,30000000000000004.
  const total = pendientes.reduce((suma, a) => suma + Math.round(Number(a.importe) * 100), 0) / 100

  return (
    <>
      <dl className="kpis">
        <Kpi
          nombre="Te deben en total"
          valor={euros(total)}
          tipo="pendiente"
          nota={
            pendientes.length === 1 ? '1 trabajo sin cobrar' : `${pendientes.length} trabajos sin cobrar`
          }
        />
      </dl>

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <section className="tarjeta cobros">
        <div className="tarjeta-cabecera">
          <h2>Sin cobrar</h2>
        </div>
        {cargando ? (
          <Esqueleto />
        ) : pendientes.length === 0 ? (
          <Vacio icono={PartyPopper} titulo="No te debe nadie">
            Todo lo que has hecho está cobrado.
          </Vacio>
        ) : (
          <ul className="lista">
            {pendientes.map((a) => (
              <FilaMovimiento
                key={a.id}
                apunte={a}
                detalle={antiguedad(a.fecha)}
                onCobrar={() =>
                  void accion(async () => {
                    await marcarCobrado(token, a.id)
                    avisar(`Cobrado · ${a.concepto} · ${euros(a.importe)}`)
                  })
                }
              >
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
              </FilaMovimiento>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
