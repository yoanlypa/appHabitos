/**
 * Finanzas: todo el dinero del mes en una pantalla.
 *
 * Arriba el resumen (cobrado, pendiente, gastos, neto) que da el backend —
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
  descargarCsv,
  marcarCobrado,
  movimientos,
  resumenMes,
  TokenInvalido,
  type Apunte,
  type Resumen,
} from '../api'
import { Cobros } from './Cobros'
import { euros, fechaCorta, iso, MESES } from '../utiles'

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
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [filtro, setFiltro] = useState<Filtro>('todo')
  const [lista, setLista] = useState<Apunte[]>([])
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [recargas, setRecargas] = useState(0)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')

  const desde = iso(new Date(anio, mes - 1, 1))
  const hasta = iso(new Date(anio, mes, 0))
  const esEsteMes = anio === hoy.getFullYear() && mes === hoy.getMonth() + 1

  function fallo(e: unknown) {
    if (e instanceof TokenInvalido) return onTokenInvalido()
    setError(e instanceof Error ? e.message : 'Algo ha fallado')
  }

  useEffect(() => {
    if (vista !== 'movimientos') return
    let cancelado = false
    Promise.all([movimientos(token, desde, hasta), resumenMes(token, anio, mes)])
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
  }, [token, vista, anio, mes, desde, hasta, recargas, onTokenInvalido])

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

  function moverMes(paso: number) {
    const d = new Date(anio, mes - 1 + paso, 1)
    setCargando(true)
    setAnio(d.getFullYear())
    setMes(d.getMonth() + 1)
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
          <div className="selector-mes">
            <button className="mini" onClick={() => moverMes(-1)} aria-label="Mes anterior">
              ‹
            </button>
            <strong>
              {MESES[mes - 1]} {anio}
            </strong>
            <button
              className="mini"
              onClick={() => moverMes(1)}
              disabled={esEsteMes}
              aria-label="Mes siguiente"
            >
              ›
            </button>
          </div>

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

          <section className="apuntes">
            {cargando ? (
              <p className="vacio">Cargando…</p>
            ) : porDia.length === 0 ? (
              <p className="vacio">
                {filtro === 'tickets'
                  ? 'No hay tickets este mes. Mándale una foto al bot o usa «Escanear ticket» en Hoy.'
                  : 'Nada anotado este mes.'}
              </p>
            ) : (
              porDia.map(([fecha, apuntes]) => (
                <div key={fecha} className="dia">
                  <h3>{fechaCorta(fecha)}</h3>
                  <ul>
                    {apuntes.map((a) => (
                      <li key={a.id} className={a.tipo}>
                        <span className="concepto">
                          {a.concepto}
                          {a.factura_id && (
                            <button
                              className="mini factura"
                              title="Ver el ticket en PDF"
                              onClick={() => void accion(() => abrirFactura(token, a.factura_id!))}
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
                            onClick={() => void accion(() => marcarCobrado(token, a.id))}
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
              Tickets de {MESES[mes - 1]} en PDF
            </button>
            <button
              className="enlace"
              onClick={() => void accion(() => descargarCsv(token, desde, hasta))}
            >
              {MESES[mes - 1]} en CSV
            </button>
          </footer>
        </>
      )}
    </section>
  )
}
