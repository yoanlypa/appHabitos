/**
 * Clientes: la lista ordenada por quién debe más, y la ficha de cada uno.
 *
 * La lista se ordena por deuda a propósito. Un listado alfabético es bonito
 * pero no contesta a la pregunta con la que se abre esta pantalla, que es
 * "¿quién me debe dinero?".
 */
import { useCallback, useEffect, useState } from 'react'
import {
  borrarCliente,
  crearCliente,
  fichaCliente,
  listarClientes,
  marcarCobrado,
  TokenInvalido,
  type FichaCliente,
  type ClienteListado,
} from '../api'
import { euros, fechaCorta, hhmm } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

export function Clientes({ token, onTokenInvalido }: Props) {
  const [lista, setLista] = useState<ClienteListado[]>([])
  const [abierto, setAbierto] = useState<number | null>(null)
  const [ficha, setFicha] = useState<FichaCliente | null>(null)
  const [buscar, setBuscar] = useState('')
  const [nuevo, setNuevo] = useState(false)
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')

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
        const datos = await listarClientes(token, buscar.trim() || undefined)
        if (!cancelado) {
          setLista(datos)
          setError('')
        }
      } catch (e) {
        if (!cancelado) fallo(e)
      }
    }
    void cargar()
    return () => {
      cancelado = true
    }
  }, [token, buscar, recargas, fallo])

  useEffect(() => {
    let cancelado = false
    async function cargar() {
      if (abierto === null) {
        setFicha(null)
        return
      }
      try {
        const f = await fichaCliente(token, abierto)
        if (!cancelado) setFicha(f)
      } catch (e) {
        if (!cancelado) fallo(e)
      }
    }
    void cargar()
    return () => {
      cancelado = true
    }
  }, [token, abierto, recargas, fallo])

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      fallo(e)
    }
  }

  async function guardarNuevo(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const formulario = e.currentTarget
    const datos = new FormData(formulario)
    const nombre = String(datos.get('nombre') ?? '').trim()
    if (!nombre) return
    await accion(async () => {
      await crearCliente(token, {
        nombre,
        telefono: String(datos.get('telefono') ?? '').trim() || null,
        direccion: String(datos.get('direccion') ?? '').trim() || null,
      })
      formulario.reset()
      setNuevo(false)
    })
  }

  // ---- Ficha de un cliente ----
  if (abierto !== null && ficha) {
    const c = ficha.cliente
    return (
      <section className="ficha">
        <button className="enlace" onClick={() => setAbierto(null)}>
          ‹ Todos los clientes
        </button>

        <h2 className="ficha-nombre">{c.nombre}</h2>
        <p className="ayuda">
          {c.telefono && (
            <a className="tel" href={`tel:${c.telefono}`}>
              {c.telefono}
            </a>
          )}
          {c.telefono && c.direccion ? ' · ' : ''}
          {c.direccion}
        </p>

        <div className="totales">
          <dl>
            <div>
              <dt>Te debe</dt>
              <dd className={Number(ficha.debe) > 0 ? 'pendiente' : ''}>{euros(ficha.debe)}</dd>
            </div>
            <div>
              <dt>Ya cobrado</dt>
              <dd className="cobrado">{euros(ficha.cobrado)}</dd>
            </div>
          </dl>
        </div>

        <h2>Trabajos y gastos</h2>
        {ficha.apuntes.length === 0 ? (
          <p className="vacio">Todavía no le has hecho nada.</p>
        ) : (
          <ul>
            {ficha.apuntes.map((a) => (
              <li key={a.id} className={a.tipo}>
                <span className="concepto">
                  {a.concepto}
                  <small>{fechaCorta(a.fecha)}</small>
                </span>
                <span className="importe">
                  {a.tipo === 'gasto' ? '−' : ''}
                  {euros(a.importe)}
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

        <h2>Citas</h2>
        {ficha.citas.length === 0 ? (
          <p className="vacio">Sin citas.</p>
        ) : (
          <ul>
            {ficha.citas.map((cita) => (
              <li key={cita.id} className={cita.hecha ? 'cita hecha' : 'cita'}>
                <span className="hora">{hhmm(cita.hora) ?? '—'}</span>
                <span className="concepto">
                  {cita.titulo}
                  <small>{fechaCorta(cita.fecha)}</small>
                </span>
              </li>
            ))}
          </ul>
        )}

        {error && <p className="error">{error}</p>}

        <footer>
          <button
            className="enlace peligro"
            onClick={() => {
              if (confirm(`¿Borrar a ${c.nombre}? Sus trabajos y gastos se conservan.`)) {
                void accion(async () => {
                  await borrarCliente(token, c.id)
                  setAbierto(null)
                })
              }
            }}
          >
            Borrar cliente
          </button>
        </footer>
      </section>
    )
  }

  // ---- Listado ----
  return (
    <section className="apuntes">
      <div className="titulo-fila">
        <h2>Clientes</h2>
        <button className="enlace" onClick={() => setNuevo((v) => !v)}>
          {nuevo ? 'Cancelar' : '+ Cliente'}
        </button>
      </div>

      {nuevo && (
        <form className="ficha-form" onSubmit={guardarNuevo}>
          <input name="nombre" placeholder="Nombre" autoFocus aria-label="Nombre" />
          <div className="fila">
            <input name="telefono" type="tel" placeholder="Teléfono" aria-label="Teléfono" />
          </div>
          <input name="direccion" placeholder="Dirección" aria-label="Dirección" />
          <button type="submit">Guardar cliente</button>
        </form>
      )}

      <input
        className="buscador"
        value={buscar}
        onChange={(e) => setBuscar(e.target.value)}
        placeholder="Buscar por nombre"
        aria-label="Buscar cliente"
      />

      {error && <p className="error">{error}</p>}

      {lista.length === 0 ? (
        <p className="vacio">
          {buscar ? 'Ningún cliente con ese nombre.' : 'Todavía no has dado de alta a nadie.'}
        </p>
      ) : (
        <ul>
          {lista.map(({ cliente, debe, total_trabajos }) => (
            <li key={cliente.id} className="cliente">
              <button className="fila-cliente" onClick={() => setAbierto(cliente.id)}>
                <span className="concepto">
                  {cliente.nombre}
                  <small>
                    {total_trabajos} {total_trabajos === 1 ? 'trabajo' : 'trabajos'}
                    {cliente.telefono ? ` · ${cliente.telefono}` : ''}
                  </small>
                </span>
                {Number(debe) > 0 && <span className="importe pendiente">{euros(debe)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
