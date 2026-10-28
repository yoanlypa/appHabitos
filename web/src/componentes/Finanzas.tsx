/**
 * Finanzas: todo el dinero de un periodo en una pantalla.
 *
 * El periodo se elige arriba: hoy, este mes, el anterior, este año, el
 * anterior o unas fechas a mano. Debajo, el resumen (cobrado, pendiente, gastos, neto) que da el backend —
 * aquí no se suma nada, que los importes van en céntimos allí. Debajo, los
 * movimientos del mes con filtros: trabajos, gastos, tickets escaneados y lo
 * pendiente de cobro. Los tickets llevan 🧾 para abrir su PDF.
 *
 * "Por cobrar" es la antigua pestaña Cobros, metida aquí dentro: lo que te
 * deben es parte de tus finanzas, y así la barra de abajo no se llena.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  abrirFactura,
  abrirFacturasDelPeriodo,
  borrarApunte,
  crearMovimiento,
  editarApunte,
  descargarCsv,
  marcarCobrado,
  movimientos,
  resumenRango,
  TokenInvalido,
  type Apunte,
  type DatosMovimiento,
  type Resumen,
} from '../api'
import { Cobros } from './Cobros'
import { EscanerFactura } from './EscanerFactura'
import { FormMovimiento } from './FormMovimiento'
import { euros, fechaCorta, iso, MESES } from '../utiles'

const PERIODOS = [
  { id: 'hoy', nombre: 'Hoy' },
  { id: 'mes', nombre: 'Este mes' },
  { id: 'mes_anterior', nombre: 'Mes anterior' },
  { id: 'anio', nombre: 'Este año' },
  { id: 'anio_anterior', nombre: 'Año anterior' },
  { id: 'personalizado', nombre: 'Fechas…' },
] as const
type Periodo = (typeof PERIODOS)[number]['id']

/** Las fechas de cada periodo, desde y hasta incluidas, en hora local. */
function rangoDe(periodo: Periodo, hoy: Date): [string, string] {
  const a = hoy.getFullYear()
  const m = hoy.getMonth()
  switch (periodo) {
    case 'hoy':
      return [iso(hoy), iso(hoy)]
    case 'mes':
      return [iso(new Date(a, m, 1)), iso(hoy)]
    case 'mes_anterior':
      return [iso(new Date(a, m - 1, 1)), iso(new Date(a, m, 0))]
    case 'anio':
      return [iso(new Date(a, 0, 1)), iso(hoy)]
    case 'anio_anterior':
      return [iso(new Date(a - 1, 0, 1)), iso(new Date(a - 1, 11, 31))]
    default:
      return [iso(new Date(a, m, 1)), iso(hoy)]
  }
}

/** Cómo se nombra el periodo en los botones de descarga y en los vacíos. */
function titulo(periodo: Periodo, desde: string, hasta: string, hoy: Date) {
  const a = hoy.getFullYear()
  const m = hoy.getMonth()
  switch (periodo) {
    case 'hoy':
      return 'hoy'
    case 'mes':
      return MESES[m]
    case 'mes_anterior':
      return MESES[(m + 11) % 12]
    case 'anio':
      return String(a)
    case 'anio_anterior':
      return String(a - 1)
    default:
      return desde === hasta ? fechaCorta(desde) : `${fechaCorta(desde)} – ${fechaCorta(hasta)}`
  }
}

type Props = {
  token: string
  onTokenInvalido: () => void
}

const FILTROS = [
  { id: 'todo', nombre: 'Todo' },
  { id: 'trabajo', nombre: 'Trabajos' },
  { id: 'gasto', nombre: 'Gastos' },
  { id: 'tickets', nombre: 'Tickets' },
] as const
type Filtro = (typeof FILTROS)[number]['id']

function pasa(a: Apunte, filtro: Filtro) {
  if (filtro === 'todo') return true
  if (filtro === 'tickets') return a.factura_id !== null
  return a.tipo === filtro
}

export function Finanzas({ token, onTokenInvalido }: Props) {
  const hoy = new Date()
  const [vista, setVista] = useState<'movimientos' | 'cobrar'>('movimientos')
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  // Las fechas a mano: empiezan en el mes en curso, que es lo más pedido.
  const [propias, setPropias] = useState<[string, string]>(() => rangoDe('mes', new Date()))
  const [filtro, setFiltro] = useState<Filtro>('todo')
  const [lista, setLista] = useState<Apunte[]>([])
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [recargas, setRecargas] = useState(0)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  // undefined: cerrado · null: añadir uno nuevo · Apunte: editar ese
  const [editando, setEditando] = useState<Apunte | null | undefined>(undefined)

  const [desde, hasta] = periodo === 'personalizado' ? propias : rangoDe(periodo, hoy)
  const rangoValido = desde <= hasta
  const nombre = titulo(periodo, desde, hasta, hoy)

  function fallo(e: unknown) {
    if (e instanceof TokenInvalido) return onTokenInvalido()
    setError(e instanceof Error ? e.message : 'Algo ha fallado')
  }

  useEffect(() => {
    if (vista !== 'movimientos' || !rangoValido) return
    let cancelado = false
    Promise.all([movimientos(token, desde, hasta), resumenRango(token, desde, hasta)])
      .then(([apuntes, totales]) => {
        if (cancelado) return
        setLista(apuntes)
        setResumen(totales)
        setError('')
      })
      .catch((e) => {
        if (cancelado) return
        if (e instanceof TokenInvalido) return onTokenInvalido()
        setError(e instanceof Error ? e.message : 'No se han podido cargar los movimientos')
      })
      .finally(() => !cancelado && setCargando(false))
    return () => {
      cancelado = true
    }
  }, [token, vista, desde, hasta, rangoValido, recargas, onTokenInvalido])

  const visibles = useMemo(() => lista.filter((a) => pasa(a, filtro)), [lista, filtro])
  const cuantos = useMemo(
    () => Object.fromEntries(FILTROS.map((f) => [f.id, lista.filter((a) => pasa(a, f.id)).length])),
    [lista],
  )
  // Agrupados por día: así se lee como un extracto del banco.
  const porDia = useMemo(() => {
    const grupos: [string, Apunte[]][] = []
    for (const a of visibles) {
      const ultimo = grupos[grupos.length - 1]
      if (ultimo && ultimo[0] === a.fecha) ultimo[1].push(a)
      else grupos.push([a.fecha, [a]])
    }
    return grupos
  }, [visibles])

  function elegir(nuevo: Periodo) {
    setPeriodo(nuevo)
    setCargando(true)
  }

  /** Guarda lo del formulario: crea uno nuevo o manda solo lo que cambió. */
  async function guardar(datos: DatosMovimiento) {
    if (editando) {
      const cambios: Partial<DatosMovimiento> = {}
      for (const clave of Object.keys(datos) as (keyof DatosMovimiento)[]) {
        const antes = clave === 'importe' ? Number(editando.importe) : editando[clave]
        const ahora = clave === 'importe' ? Number(datos.importe) : datos[clave]
        if (antes !== ahora) Object.assign(cambios, { [clave]: datos[clave] })
      }
      if (Object.keys(cambios).length) await editarApunte(token, editando.id, cambios)
    } else {
      await crearMovimiento(token, datos)
    }
    setEditando(undefined)
    setRecargas((n) => n + 1)
  }

  async function borrar() {
    if (!editando) return
    await borrarApunte(token, editando.id)
    setEditando(undefined)
    setRecargas((n) => n + 1)
  }

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      fallo(e)
    }
  }

  return (
    <section className="finanzas">
      <div className="pestanas">
        <button
          className={vista === 'movimientos' ? 'activa' : ''}
          onClick={() => setVista('movimientos')}
        >
          Movimientos
        </button>
        <button className={vista === 'cobrar' ? 'activa' : ''} onClick={() => setVista('cobrar')}>
          Por cobrar
        </button>
      </div>

      {vista === 'cobrar' && <Cobros token={token} onTokenInvalido={onTokenInvalido} />}

      {vista === 'movimientos' && (
        <>
          <div className="filtros periodos">
            {PERIODOS.map((p) => (
              <button
                key={p.id}
                className={periodo === p.id ? 'activa' : ''}
                onClick={() => elegir(p.id)}
              >
                {p.nombre}
              </button>
            ))}
          </div>

          {periodo === 'personalizado' && (
            <div className="rango-propio">
              <label>
                Desde
                <input
                  type="date"
                  value={propias[0]}
                  max={iso(hoy)}
                  onChange={(e) => {
                    setPropias([e.target.value, propias[1]])
                    setCargando(true)
                  }}
                />
              </label>
              <label>
                Hasta
                <input
                  type="date"
                  value={propias[1]}
                  max={iso(hoy)}
                  onChange={(e) => {
                    setPropias([propias[0], e.target.value])
                    setCargando(true)
                  }}
                />
              </label>
            </div>
          )}
          {!rangoValido && <p className="error">La fecha «desde» va después de «hasta».</p>}

          {resumen && (
            <section className="totales">
              <dl>
                <div>
                  <dt>Cobrado</dt>
                  <dd className="cobrado">{euros(resumen.cobrado)}</dd>
                </div>
                <div>
                  <dt>Pendiente</dt>
                  <dd className="pendiente">{euros(resumen.pendiente)}</dd>
                </div>
                <div>
                  <dt>Gastos</dt>
                  <dd className="gasto">{euros(resumen.gastos)}</dd>
                </div>
                <div className="neto">
                  <dt>Neto</dt>
                  <dd>{euros(resumen.neto)}</dd>
                </div>
              </dl>
            </section>
          )}

          <div className="filtros">
            {FILTROS.map((f) => (
              <button
                key={f.id}
                className={filtro === f.id ? 'activa' : ''}
                onClick={() => setFiltro(f.id)}
              >
                {f.nombre} <small>{cuantos[f.id] ?? 0}</small>
              </button>
            ))}
          </div>

          {error && <p className="error">{error}</p>}

          <div className="anadir">
            {filtro === 'tickets' ? (
              <EscanerFactura
                token={token}
                onGuardado={() => setRecargas((n) => n + 1)}
                onError={fallo}
              />
            ) : (
              <button type="button" className="escanear" onClick={() => setEditando(null)}>
                + Añadir {filtro === 'gasto' ? 'gasto' : filtro === 'trabajo' ? 'trabajo' : 'trabajo o gasto'}
              </button>
            )}
          </div>

          {editando !== undefined && (
            <FormMovimiento
              apunte={editando}
              tipoInicial={filtro === 'gasto' ? 'gasto' : 'trabajo'}
              onGuardar={guardar}
              onBorrar={editando ? borrar : undefined}
              onCerrar={() => setEditando(undefined)}
            />
          )}

          <section className="apuntes">
            {!rangoValido ? null : cargando ? (
              <p className="vacio">Cargando…</p>
            ) : porDia.length === 0 ? (
              <p className="vacio">
                {filtro === 'tickets'
                  ? `No hay tickets en ${nombre}. Mándale una foto al bot o usa «Escanear ticket» en Hoy.`
                  : `Nada anotado en ${nombre}.`}
              </p>
            ) : (
              porDia.map(([fecha, apuntes]) => (
                <div key={fecha} className="dia">
                  <h3>
                    {fechaCorta(fecha)}
                    {fecha.slice(0, 4) !== String(hoy.getFullYear()) && ` ${fecha.slice(0, 4)}`}
                  </h3>
                  <ul>
                    {apuntes.map((a) => (
                      <li
                        key={a.id}
                        className={`${a.tipo} tocable`}
                        onClick={() => setEditando(a)}
                        title="Tocar para editar o borrar"
                      >
                        <span className="concepto">
                          {a.concepto}
                          {a.factura_id && (
                            <button
                              className="mini factura"
                              title="Ver el ticket en PDF"
                              onClick={(e) => {
                                e.stopPropagation()
                                void accion(() => abrirFactura(token, a.factura_id!))
                              }}
                            >
                              🧾
                            </button>
                          )}
                        </span>
                        <span className={`importe ${a.tipo}`}>
                          {a.tipo === 'gasto' ? '−' : ''}
                          {euros(a.importe)}
                        </span>
                        {a.pendiente && (
                          <button
                            className="cobrar"
                            onClick={(e) => {
                              e.stopPropagation()
                              void accion(() => marcarCobrado(token, a.id))
                            }}
                          >
                            Cobrar
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))
            )}
          </section>

          <footer>
            <button
              className="enlace"
              onClick={() => void accion(() => abrirFacturasDelPeriodo(token, desde, hasta))}
            >
              Tickets de {nombre} en PDF
            </button>
            <button
              className="enlace"
              onClick={() => void accion(() => descargarCsv(token, desde, hasta))}
            >
              CSV de {nombre}
            </button>
          </footer>
        </>
      )}
    </section>
  )
}
