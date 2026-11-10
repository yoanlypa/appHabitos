/**
 * Clientes: la lista ordenada por quién debe más, y la ficha de cada uno.
 *
 * La lista se ordena por deuda a propósito. Un listado alfabético es bonito
 * pero no contesta a la pregunta con la que se abre esta pantalla, que es
 * "¿quién me debe dinero?".
 *
 * En el ordenador la lista se queda a la izquierda y la ficha se abre al
 * lado, para pasar de un cliente a otro sin ir y volver. En el móvil la ficha
 * ocupa la pantalla y tiene su botón de volver.
 */
import { ArrowLeft, MapPin, Phone, Plus, Search, Trash2, Users } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  abrirFactura,
  borrarCliente,
  crearCliente,
  fichaCliente,
  listarClientes,
  marcarCobrado,
  TokenInvalido,
  type FichaCliente,
  type ClienteListado,
} from '../api'
import { confirmar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { Avatar, Cabecera, ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { diaRelativo, euros, fechaCorta, hhmm } from '../utiles'
import { FilaMovimiento } from './FilaMovimiento'

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
  const [cargando, setCargando] = useState(true)
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
      } finally {
        if (!cancelado) setCargando(false)
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
    const datos = new FormData(e.currentTarget)
    const nombre = String(datos.get('nombre') ?? '').trim()
    if (!nombre) return
    await accion(async () => {
      const creado = await crearCliente(token, {
        nombre,
        telefono: String(datos.get('telefono') ?? '').trim() || null,
        direccion: String(datos.get('direccion') ?? '').trim() || null,
      })
      setNuevo(false)
      setAbierto(creado.id)
    })
  }

  async function borrar(id: number, nombre: string) {
    const si = await confirmar({
      titulo: `¿Borrar a ${nombre}?`,
      texto: 'Sus trabajos y gastos se conservan, pero dejan de estar a su nombre.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (!si) return
    void accion(async () => {
      await borrarCliente(token, id)
      setAbierto(null)
    })
  }

  const c = ficha?.cliente

  return (
    <>
      <Cabecera titulo="Clientes" subtitulo="Ordenados por lo que te deben.">
        <button className="boton" onClick={() => setNuevo(true)}>
          <Plus size={18} />
          Nuevo cliente
        </button>
      </Cabecera>

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <div className={abierto !== null ? 'clientes con-ficha' : 'clientes'}>
        <section className="tarjeta clientes-lista">
          <label className="buscador">
            <Search size={17} />
            <input
              value={buscar}
              onChange={(e) => setBuscar(e.target.value)}
              placeholder="Buscar por nombre"
              aria-label="Buscar cliente"
            />
          </label>

          {cargando ? (
            <Esqueleto />
          ) : lista.length === 0 ? (
            <Vacio icono={Users} titulo={buscar ? 'Ningún cliente con ese nombre' : 'Todavía no hay clientes'}>
              {!buscar && 'Al darlos de alta, los apuntes que los nombren se cuelgan solos de ellos.'}
            </Vacio>
          ) : (
            <ul className="lista">
              {lista.map(({ cliente, debe, total_trabajos }) => (
                <li
                  key={cliente.id}
                  className={abierto === cliente.id ? 'fila tocable elegida' : 'fila tocable'}
                  role="button"
                  tabIndex={0}
                  onClick={() => setAbierto(cliente.id)}
                  onKeyDown={(e) => e.key === 'Enter' && setAbierto(cliente.id)}
                >
                  <Avatar nombre={cliente.nombre} />
                  <span className="principal">
                    {cliente.nombre}
                    <small>
                      {total_trabajos} {total_trabajos === 1 ? 'trabajo' : 'trabajos'}
                      {cliente.telefono ? ` · ${cliente.telefono}` : ''}
                    </small>
                  </span>
                  {Number(debe) > 0 && <span className="pastilla pendiente">{euros(debe)}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="clientes-ficha">
          {abierto === null ? (
            <div className="tarjeta">
              <Vacio icono={Users} titulo="Elige un cliente">
                Verás lo que te debe, sus trabajos y sus citas.
              </Vacio>
            </div>
          ) : !ficha || !c ? (
            <div className="tarjeta">
              <Esqueleto />
            </div>
          ) : (
            <>
              <button className="enlace gris volver" onClick={() => setAbierto(null)}>
                <ArrowLeft size={16} />
                Todos los clientes
              </button>

              <div className="tarjeta ficha-cabecera">
                <Avatar nombre={c.nombre} grande />
                <div className="principal">
                  <h2>{c.nombre}</h2>
                  <p className="contacto">
                    {c.telefono && (
                      <a href={`tel:${c.telefono}`}>
                        <Phone size={14} /> {c.telefono}
                      </a>
                    )}
                    {c.direccion && (
                      <span>
                        <MapPin size={14} /> {c.direccion}
                      </span>
                    )}
                    {!c.telefono && !c.direccion && <span>Sin teléfono ni dirección</span>}
                  </p>
                </div>
                <button
                  className="boton-icono peligro"
                  onClick={() => void borrar(c.id, c.nombre)}
                  aria-label="Borrar cliente"
                  title="Borrar cliente"
                >
                  <Trash2 size={18} />
                </button>
              </div>

              <dl className="kpis">
                <Kpi
                  nombre="Te debe"
                  valor={euros(ficha.debe)}
                  tipo={Number(ficha.debe) > 0 ? 'pendiente' : undefined}
                />
                <Kpi nombre="Ya cobrado" valor={euros(ficha.cobrado)} tipo="cobrado" />
              </dl>

              <div className="tarjeta">
                <div className="tarjeta-cabecera">
                  <h2>Trabajos y gastos</h2>
                </div>
                {ficha.apuntes.length === 0 ? (
                  <Vacio>Todavía no le has hecho nada.</Vacio>
                ) : (
                  <ul className="lista">
                    {ficha.apuntes.map((a) => (
                      <FilaMovimiento
                        key={a.id}
                        apunte={a}
                        detalle={fechaCorta(a.fecha)}
                        onCobrar={() => void accion(() => marcarCobrado(token, a.id))}
                        onTicket={() => void accion(() => abrirFactura(token, a.factura_id!))}
                      />
                    ))}
                  </ul>
                )}
              </div>

              <div className="tarjeta">
                <div className="tarjeta-cabecera">
                  <h2>Citas</h2>
                </div>
                {ficha.citas.length === 0 ? (
                  <Vacio>Sin citas.</Vacio>
                ) : (
                  <ul className="lista">
                    {ficha.citas.map((cita) => (
                      <li key={cita.id} className={cita.hecha ? 'fila hecha' : 'fila'}>
                        <span className="principal">
                          {cita.titulo}
                          <small>
                            {diaRelativo(cita.fecha)}
                            {hhmm(cita.hora) ? ` · ${hhmm(cita.hora)}` : ''}
                          </small>
                        </span>
                        {cita.hecha && <span className="pastilla">Hecha</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {nuevo && (
        <Modal titulo="Nuevo cliente" onCerrar={() => setNuevo(false)}>
          <form className="formulario" onSubmit={guardarNuevo}>
            <label className="campo">
              Nombre
              <input name="nombre" placeholder="Ana Ruiz" autoFocus required />
            </label>
            <label className="campo">
              <span>
                Teléfono <small>(opcional)</small>
              </span>
              <input name="telefono" type="tel" inputMode="tel" />
            </label>
            <label className="campo">
              <span>
                Dirección <small>(opcional)</small>
              </span>
              <input name="direccion" />
            </label>
            <div className="botones">
              <span className="derecha">
                <button type="button" className="boton secundario" onClick={() => setNuevo(false)}>
                  Cancelar
                </button>
                <button type="submit" className="boton">
                  Guardar cliente
                </button>
              </span>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}
