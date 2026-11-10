/**
 * Finanzas: todo el dinero de un periodo en una pantalla.
 *
 * El periodo se elige arriba: hoy, este mes, el anterior, este año, el
 * anterior o unas fechas a mano. Debajo, el resumen (cobrado, pendiente,
 * gastos, neto) que da el backend —aquí no se suma nada, que los importes van
 * en céntimos allí—, el año mes a mes en un gráfico, y los movimientos del
 * periodo con filtros: trabajos, gastos, tickets escaneados y facturas
 * propias. Los que tienen ticket llevan un botón para abrir su PDF.
 *
 * Tocar un mes del gráfico lo pone como periodo: es la forma rápida de ir a
 * "marzo" sin escribir fechas.
 *
 * "Por cobrar" es la antigua pestaña Cobros, metida aquí dentro: lo que te
 * deben es parte de tus finanzas, y así la barra de abajo no se llena.
 *
 * "Gestoría" es lo mismo mirado para mandarlo: solo lo que factura Yoa y
 * sus gastos, por mes o por trimestre (`Gestoria.tsx`).
 */
import { Download, FileText, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  abrirFactura,
  abrirFacturasDelPeriodo,
  descargarCsv,
  marcarCobrado,
  movimientos,
  resumenRango,
  TokenInvalido,
  type Apunte,
  type Resumen,
} from '../api'
import { Cabecera, ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { diaRelativo, euros, fechaCorta, iso, MESES } from '../utiles'
import { Cobros } from './Cobros'
import { EditorMovimiento } from './EditorMovimiento'
import { EscanerFactura } from './EscanerFactura'
import { FilaMovimiento } from './FilaMovimiento'
import { Gestoria } from './Gestoria'
import { GraficoMeses } from './GraficoMeses'

const VISTAS = [
  { id: 'movimientos', nombre: 'Movimientos' },
  { id: 'cobrar', nombre: 'Por cobrar' },
  { id: 'gestoria', nombre: 'Gestoría' },
] as const
type Vista = (typeof VISTAS)[number]['id']

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
    default: {
      // Un mes entero (o lo que va del actual), que es lo que da el gráfico
      // al tocarlo: se llama por su nombre y no "1 mar – 31 mar".
      const [da, dm, dd] = desde.split('-').map(Number)
      const ultimo = iso(new Date(da, dm, 0))
      if (dd === 1 && hasta.slice(0, 7) === desde.slice(0, 7) && (hasta === ultimo || hasta === iso(hoy))) {
        return da === a ? MESES[dm - 1] : `${MESES[dm - 1]} de ${da}`
      }
      return desde === hasta ? fechaCorta(desde) : `${fechaCorta(desde)} – ${fechaCorta(hasta)}`
    }
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
  { id: 'emitidas', nombre: 'Mis facturas' },
] as const
type Filtro = (typeof FILTROS)[number]['id']

function pasa(a: Apunte, filtro: Filtro) {
  if (filtro === 'todo') return true
  if (filtro === 'tickets') return a.factura_id !== null && !a.factura_emitida
  if (filtro === 'emitidas') return a.factura_emitida
  return a.tipo === filtro
}

export function Finanzas({ token, onTokenInvalido }: Props) {
  const hoy = new Date()
  const [vista, setVista] = useState<Vista>('movimientos')
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

  const fallo = useCallback(
    (e: unknown) => {
      if (e instanceof TokenInvalido) return onTokenInvalido()
      setError(e instanceof Error ? e.message : 'Algo ha fallado')
    },
    [onTokenInvalido],
  )

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
        if (!cancelado) fallo(e)
      })
      .finally(() => !cancelado && setCargando(false))
    return () => {
      cancelado = true
    }
  }, [token, vista, desde, hasta, rangoValido, recargas, fallo])

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

  function elegirFechas(nuevas: [string, string]) {
    setPropias(nuevas)
    setPeriodo('personalizado')
    setCargando(true)
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

  const deFacturas = filtro === 'tickets' || filtro === 'emitidas'

  return (
    <>
      <Cabecera titulo="Finanzas">
        <button className="boton" onClick={() => setEditando(null)}>
          <Plus size={18} />
          Añadir
        </button>
      </Cabecera>

      <Segmentado opciones={VISTAS} valor={vista} onCambio={setVista} etiqueta="Vista" />

      {vista === 'cobrar' && <Cobros key={recargas} token={token} onTokenInvalido={onTokenInvalido} />}

      {vista === 'gestoria' && (
        <>
          <ErrorEnLinea>{error}</ErrorEnLinea>
          <Gestoria token={token} recargas={recargas} onAbrir={setEditando} onFallo={fallo} />
        </>
      )}

      {vista === 'movimientos' && (
        <>
          <div className="chips" role="tablist" aria-label="Periodo">
            {PERIODOS.map((p) => (
              <button
                key={p.id}
                role="tab"
                aria-selected={periodo === p.id}
                className={periodo === p.id ? 'chip activa' : 'chip'}
                onClick={() => elegir(p.id)}
              >
                {p.nombre}
              </button>
            ))}
          </div>

          {periodo === 'personalizado' && (
            <div className="dos-campos rango-propio">
              <label className="campo">
                Desde
                <input
                  type="date"
                  value={propias[0]}
                  max={iso(hoy)}
                  onChange={(e) => elegirFechas([e.target.value, propias[1]])}
                />
              </label>
              <label className="campo">
                Hasta
                <input
                  type="date"
                  value={propias[1]}
                  max={iso(hoy)}
                  onChange={(e) => elegirFechas([propias[0], e.target.value])}
                />
              </label>
            </div>
          )}
          {!rangoValido && <ErrorEnLinea>La fecha «desde» va después de «hasta».</ErrorEnLinea>}

          <dl className="kpis cuatro">
            <Kpi nombre="Cobrado" valor={resumen ? euros(resumen.cobrado) : '—'} tipo="cobrado" />
            <Kpi nombre="Pendiente" valor={resumen ? euros(resumen.pendiente) : '—'} tipo="pendiente" />
            <Kpi nombre="Gastos" valor={resumen ? euros(resumen.gastos) : '—'} tipo="gasto" />
            <Kpi nombre="Neto" valor={resumen ? euros(resumen.neto) : '—'} tipo="neto" />
          </dl>

          <GraficoMeses
            token={token}
            recargas={recargas}
            onFallo={fallo}
            onMes={(primero, ultimo) => elegirFechas([primero, ultimo])}
          />

          <ErrorEnLinea>{error}</ErrorEnLinea>

          <section className="tarjeta movimientos">
            <div className="tarjeta-cabecera">
              <h2>
                Movimientos <span className="apagado">· {nombre}</span>
              </h2>
            </div>

            <div className="chips" role="tablist" aria-label="Filtro">
              {FILTROS.map((f) => (
                <button
                  key={f.id}
                  role="tab"
                  aria-selected={filtro === f.id}
                  className={filtro === f.id ? 'chip activa' : 'chip'}
                  onClick={() => setFiltro(f.id)}
                >
                  {f.nombre} <small>{cuantos[f.id] ?? 0}</small>
                </button>
              ))}
            </div>

            {deFacturas && (
              <EscanerFactura
                token={token}
                onGuardado={() => setRecargas((n) => n + 1)}
                onError={fallo}
              />
            )}

            {!rangoValido ? null : cargando ? (
              <Esqueleto />
            ) : porDia.length === 0 ? (
              <Vacio icono={FileText} titulo={`Nada en ${nombre}`}>
                {filtro === 'emitidas'
                  ? 'Sube el PDF de una factura tuya y entra como trabajo.'
                  : filtro === 'tickets'
                    ? 'Mándale una foto al bot o escanea un ticket aquí.'
                    : 'Lo que anotes en este periodo saldrá aquí.'}
              </Vacio>
            ) : (
              porDia.map(([fecha, apuntes]) => (
                <div key={fecha} className="dia">
                  <h3>{diaRelativo(fecha)}</h3>
                  <ul className="lista">
                    {apuntes.map((a) => (
                      <FilaMovimiento
                        key={a.id}
                        apunte={a}
                        onAbrir={() => setEditando(a)}
                        onCobrar={() => void accion(() => marcarCobrado(token, a.id))}
                        onTicket={() => void accion(() => abrirFactura(token, a.factura_id!))}
                      />
                    ))}
                  </ul>
                </div>
              ))
            )}
          </section>

          <section className="exportar">
            <h3>Para la gestoría · {nombre}</h3>
            <div>
              <button
                className="boton secundario pequeno"
                onClick={() => void accion(() => descargarCsv(token, desde, hasta))}
              >
                <Download size={15} />
                CSV
              </button>
              <button
                className="boton secundario pequeno"
                onClick={() => void accion(() => abrirFacturasDelPeriodo(token, desde, hasta))}
              >
                <Download size={15} />
                Tickets en PDF
              </button>
              <button
                className="boton secundario pequeno"
                onClick={() => void accion(() => abrirFacturasDelPeriodo(token, desde, hasta, true))}
              >
                <Download size={15} />
                Mis facturas en PDF
              </button>
            </div>
          </section>
        </>
      )}

      {editando !== undefined && (
        <EditorMovimiento
          token={token}
          apunte={editando}
          tipoInicial={filtro === 'gasto' ? 'gasto' : 'trabajo'}
          onCambio={() => setRecargas((n) => n + 1)}
          onCerrar={() => setEditando(undefined)}
        />
      )}
    </>
  )
}
