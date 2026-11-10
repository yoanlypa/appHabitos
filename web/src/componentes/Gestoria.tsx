/**
 * Lo que se manda a la gestoría de un mes o de un trimestre.
 *
 * En el resto de la app está todo junto, porque es el día a día. Aquí solo
 * sale lo de Yoa: las facturas que emite y los gastos que les corresponden
 * (las facturas recibidas). Los trabajos que factura otra empresa, y sus
 * gastos, se quedan fuera.
 *
 * Es una lista de repaso de fin de mes, así que enseña las dos mitades: lo
 * que va y lo que no. Lo que no va está a la vista a propósito, con un botón
 * para meterlo: un gasto que se olvidó marcar solo se descubre si se ve.
 *
 * Y avisa de lo que va sin su papel colgado. A la gestoría no le vale una
 * línea en una hoja; mejor saberlo hoy que cuando lo reclame.
 *
 * Qué va y qué no lo decide el backend (`gestoria` en cada apunte) y las
 * sumas también: aquí solo se reparte en la pantalla.
 */
import { Download, FileCheck2, FileWarning, Landmark } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  abrirFactura,
  abrirFacturasDelPeriodo,
  descargarCsvGestoria,
  editarApunte,
  parteGestoria,
  type Apunte,
  type ParteGestoria,
} from '../api'
import { avisar } from '../ui/avisos'
import { ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { euros, fechaCorta, iso, MESES } from '../utiles'
import { EscanerFactura } from './EscanerFactura'
import { FilaMovimiento } from './FilaMovimiento'

type Props = {
  token: string
  /** Sube cuando algo cambia fuera (se guarda un movimiento), para recargar. */
  recargas: number
  onAbrir: (apunte: Apunte) => void
  onFallo: (e: unknown) => void
}

const PERIODOS = [
  { id: 'mes', nombre: 'Este mes' },
  { id: 'mes_anterior', nombre: 'Mes anterior' },
  { id: 'trimestre', nombre: 'Este trimestre' },
  { id: 'trimestre_anterior', nombre: 'Trimestre anterior' },
  { id: 'personalizado', nombre: 'Fechas…' },
] as const
type Periodo = (typeof PERIODOS)[number]['id']

/** Las fechas de cada periodo (incluidas) y cómo se llama. */
function rangoDe(periodo: Periodo, hoy: Date): { desde: string; hasta: string; nombre: string } {
  const a = hoy.getFullYear()
  const m = hoy.getMonth()
  // El trimestre natural, que es el de los modelos: ene-mar, abr-jun...
  const t = Math.floor(m / 3)
  switch (periodo) {
    case 'mes_anterior':
      return {
        desde: iso(new Date(a, m - 1, 1)),
        hasta: iso(new Date(a, m, 0)),
        nombre: MESES[(m + 11) % 12],
      }
    case 'trimestre':
      return {
        desde: iso(new Date(a, t * 3, 1)),
        hasta: iso(hoy),
        nombre: `el ${t + 1}.º trimestre`,
      }
    case 'trimestre_anterior': {
      const inicio = new Date(a, t * 3 - 3, 1)
      const numero = Math.floor(inicio.getMonth() / 3) + 1
      return {
        desde: iso(inicio),
        hasta: iso(new Date(a, t * 3, 0)),
        nombre: `el ${numero}.º trimestre${inicio.getFullYear() !== a ? ` de ${inicio.getFullYear()}` : ''}`,
      }
    }
    default:
      return { desde: iso(new Date(a, m, 1)), hasta: iso(hoy), nombre: MESES[m] }
  }
}

export function Gestoria({ token, recargas, onAbrir, onFallo }: Props) {
  const hoy = new Date()
  const [periodo, setPeriodo] = useState<Periodo>('mes')
  const [propias, setPropias] = useState<[string, string]>(() => {
    const r = rangoDe('mes', new Date())
    return [r.desde, r.hasta]
  })
  const [parte, setParte] = useState<ParteGestoria | null>(null)
  const [propios, setPropios] = useState(0)
  const [cargando, setCargando] = useState(true)

  const elegido = rangoDe(periodo, hoy)
  const desde = periodo === 'personalizado' ? propias[0] : elegido.desde
  const hasta = periodo === 'personalizado' ? propias[1] : elegido.hasta
  const nombre =
    periodo === 'personalizado'
      ? desde === hasta
        ? `el ${fechaCorta(desde)}`
        : `${fechaCorta(desde)} – ${fechaCorta(hasta)}`
      : elegido.nombre
  const rangoValido = desde <= hasta

  useEffect(() => {
    if (!rangoValido) return
    let cancelado = false
    parteGestoria(token, desde, hasta)
      .then((p) => {
        if (!cancelado) setParte(p)
      })
      .catch((e) => {
        if (!cancelado) onFallo(e)
      })
      .finally(() => !cancelado && setCargando(false))
    return () => {
      cancelado = true
    }
  }, [token, desde, hasta, rangoValido, recargas, propios, onFallo])

  function elegir(nuevo: Periodo) {
    setPeriodo(nuevo)
    setCargando(true)
  }

  async function accion(hacer: () => Promise<unknown>) {
    try {
      await hacer()
      setPropios((n) => n + 1)
    } catch (e) {
      onFallo(e)
    }
  }

  /** Meter en la gestoría con un toque lo que se había quedado fuera. */
  function incluir(a: Apunte) {
    void accion(async () => {
      await editarApunte(token, a.id, a.tipo === 'trabajo' ? { facturado: true } : { para_gestoria: true })
      avisar(`Va a la gestoría · ${a.concepto}`)
    })
  }

  const ticket = (a: Apunte) => () => void accion(() => abrirFactura(token, a.factura_id!))
  const fuera = parte ? parte.trabajos_fuera.length + parte.gastos_fuera.length : 0

  return (
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
              onChange={(e) => {
                setPropias([e.target.value, propias[1]])
                setCargando(true)
              }}
            />
          </label>
          <label className="campo">
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
      {!rangoValido && <ErrorEnLinea>La fecha «desde» va después de «hasta».</ErrorEnLinea>}

      <dl className="kpis tres">
        <Kpi nombre="Facturado" valor={parte ? euros(parte.facturado) : '—'} tipo="cobrado" />
        <Kpi nombre="Gastos de lo facturado" valor={parte ? euros(parte.gastos) : '—'} tipo="gasto" />
        <Kpi nombre="Diferencia" valor={parte ? euros(parte.diferencia) : '—'} tipo="neto" />
      </dl>

      {parte && parte.sin_documento > 0 && (
        <p className="aviso-linea">
          <FileWarning size={18} />
          <span>
            {parte.sin_documento === 1
              ? 'Hay 1 apunte sin su factura o ticket colgado.'
              : `Hay ${parte.sin_documento} apuntes sin su factura o ticket colgado.`}{' '}
            La gestoría los va a pedir.
          </span>
        </p>
      )}

      {!rangoValido ? null : cargando || !parte ? (
        <Esqueleto />
      ) : (
        <>
          <section className="tarjeta va-gestoria">
            <div className="tarjeta-cabecera">
              <h2>
                Facturas emitidas <span className="contador">{parte.emitidas.length}</span>
              </h2>
            </div>
            {parte.emitidas.length === 0 ? (
              <Vacio icono={Landmark} titulo={`Nada facturado en ${nombre}`}>
                Marca «Lo facturo yo» en un trabajo, o sube el PDF de tu factura.
              </Vacio>
            ) : (
              <ul className="lista">
                {parte.emitidas.map((a) => (
                  <FilaMovimiento
                    key={a.id}
                    apunte={a}
                    detalle={`${fechaCorta(a.fecha)} · ${a.pendiente ? 'pendiente de cobro' : 'cobrado'}`}
                    onAbrir={() => onAbrir(a)}
                    onTicket={ticket(a)}
                  >
                    {!a.factura_id && <span className="pastilla pendiente">Sin factura</span>}
                  </FilaMovimiento>
                ))}
              </ul>
            )}
          </section>

          <section className="tarjeta va-gestoria">
            <div className="tarjeta-cabecera">
              <h2>
                Facturas recibidas <span className="contador">{parte.recibidas.length}</span>
              </h2>
            </div>
            {/* Lo que se escanea desde aquí es para la gestoría: ya viene marcado. */}
            <EscanerFactura
              token={token}
              paraGestoria
              onGuardado={() => setPropios((n) => n + 1)}
              onError={onFallo}
            />
            {parte.recibidas.length === 0 ? (
              <Vacio icono={FileCheck2} titulo={`Ningún gasto para la gestoría en ${nombre}`}>
                Van los gastos de un trabajo facturado y los que marques a mano.
              </Vacio>
            ) : (
              <ul className="lista">
                {parte.recibidas.map((a) => (
                  <FilaMovimiento
                    key={a.id}
                    apunte={a}
                    detalle={`${fechaCorta(a.fecha)} · ${a.trabajo_concepto ?? 'gasto general'}`}
                    onAbrir={() => onAbrir(a)}
                    onTicket={ticket(a)}
                  >
                    {!a.factura_id && <span className="pastilla pendiente">Sin ticket</span>}
                  </FilaMovimiento>
                ))}
              </ul>
            )}
          </section>

          {fuera > 0 && (
            <details className="tarjeta no-va">
              <summary>
                <h2>
                  No va a la gestoría <span className="contador">{fuera}</span>
                </h2>
                <span className="ayuda">Repásalo: lo que falte se mete con un toque.</span>
              </summary>

              {parte.trabajos_fuera.length > 0 && (
                <>
                  <h3>Trabajos sin facturar</h3>
                  <ul className="lista">
                    {parte.trabajos_fuera.map((a) => (
                      <FilaMovimiento
                        key={a.id}
                        apunte={a}
                        detalle={fechaCorta(a.fecha)}
                        onAbrir={() => onAbrir(a)}
                      >
                        <button
                          className="boton secundario pequeno"
                          onClick={(e) => {
                            e.stopPropagation()
                            incluir(a)
                          }}
                        >
                          Lo facturo yo
                        </button>
                      </FilaMovimiento>
                    ))}
                  </ul>
                </>
              )}

              {parte.gastos_fuera.length > 0 && (
                <>
                  <h3>Gastos</h3>
                  <ul className="lista">
                    {parte.gastos_fuera.map((a) => (
                      <FilaMovimiento
                        key={a.id}
                        apunte={a}
                        detalle={
                          a.trabajo_concepto
                            ? `${fechaCorta(a.fecha)} · de «${a.trabajo_concepto}», sin facturar`
                            : `${fechaCorta(a.fecha)} · gasto general`
                        }
                        onAbrir={() => onAbrir(a)}
                        onTicket={ticket(a)}
                      >
                        {/* El de un trabajo sigue a su trabajo: no se marca aparte. */}
                        {a.trabajo_id === null && (
                          <button
                            className="boton secundario pequeno"
                            onClick={(e) => {
                              e.stopPropagation()
                              incluir(a)
                            }}
                          >
                            Incluir
                          </button>
                        )}
                      </FilaMovimiento>
                    ))}
                  </ul>
                </>
              )}
            </details>
          )}

          <section className="exportar">
            <h3>Para mandar · {nombre}</h3>
            <div>
              <button
                className="boton secundario pequeno"
                onClick={() => void accion(() => descargarCsvGestoria(token, desde, hasta))}
              >
                <Download size={15} />
                Hoja (CSV)
              </button>
              <button
                className="boton secundario pequeno"
                onClick={() =>
                  void accion(() => abrirFacturasDelPeriodo(token, desde, hasta, true, true))
                }
              >
                <Download size={15} />
                Facturas emitidas (PDF)
              </button>
              <button
                className="boton secundario pequeno"
                onClick={() =>
                  void accion(() => abrirFacturasDelPeriodo(token, desde, hasta, false, true))
                }
              >
                <Download size={15} />
                Facturas recibidas (PDF)
              </button>
            </div>
          </section>
        </>
      )}
    </>
  )
}
