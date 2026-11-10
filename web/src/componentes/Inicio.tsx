/**
 * Inicio: el día entero en una pantalla.
 *
 * Arriba, la caja de anotar, que es lo que más se hace. Debajo, las cifras
 * (hoy, el mes o el trimestre) y cuatro tarjetas con lo que toca hoy: el
 * dinero que se ha movido, lo próximo de la agenda, los hábitos y las notas
 * sin fecha. Cada tarjeta deja hacer lo más frecuente sin salir de aquí
 * (cobrar, marcar hecho) y lleva a su pantalla para todo lo demás.
 *
 * No calcula nada: cada dato lo da el backend y aquí solo se junta. Los datos
 * se recargan subiendo `recargas`: así el efecto de carga es el único sitio
 * que pide a la API, y las acciones solo dicen "algo cambió".
 */
import { CalendarDays, Check, ChevronRight, Flame, StickyNote, Wallet } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  abrirFactura,
  listarApuntes,
  listarHabitos,
  listarNotas,
  marcarCitaHecha,
  marcarCobrado,
  marcarDiaHabito,
  marcarNotaHecha,
  proximasCitas,
  resumenDia,
  resumenMes,
  resumenTrimestre,
  TokenInvalido,
  type Apunte,
  type Cita,
  type Nota,
  type Resumen,
  type ResumenHabito,
  type ResumenTrimestre,
} from '../api'
import type { Ir } from '../secciones'
import { Cabecera, ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { diaRelativo, euros, fechaLarga, hhmm, iso, MESES, saludo } from '../utiles'
import { Captura } from './Captura'
import { EditorMovimiento } from './EditorMovimiento'
import { FilaMovimiento } from './FilaMovimiento'

type Props = {
  token: string
  onTokenInvalido: () => void
  onIr: Ir
}

const PERIODOS = [
  { id: 'dia', nombre: 'Hoy' },
  { id: 'mes', nombre: 'Este mes' },
  { id: 'trimestre', nombre: 'Trimestre' },
] as const
type Periodo = (typeof PERIODOS)[number]['id']

/** Cuántas notas y citas caben en la tarjeta antes de mandar a su pantalla. */
const A_LA_VISTA = 5

export function Inicio({ token, onTokenInvalido, onIr }: Props) {
  const hoyISO = iso(new Date())
  const [periodo, setPeriodo] = useState<Periodo>('dia')
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [trimestre, setTrimestre] = useState<ResumenTrimestre | null>(null)
  const [apuntes, setApuntes] = useState<Apunte[]>([])
  const [citas, setCitas] = useState<Cita[]>([])
  const [habitos, setHabitos] = useState<ResumenHabito[]>([])
  const [notas, setNotas] = useState<Nota[]>([])
  const [editando, setEditando] = useState<Apunte | null>(null)
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
  const recargar = useCallback(() => setRecargas((n) => n + 1), [])

  useEffect(() => {
    let cancelado = false

    async function cargar() {
      const hoy = new Date()
      try {
        const [lista, totales, tri, proximas, misHabitos, misNotas] = await Promise.all([
          listarApuntes(token),
          periodo === 'mes'
            ? resumenMes(token, hoy.getFullYear(), hoy.getMonth() + 1)
            : resumenDia(token),
          periodo === 'trimestre' ? resumenTrimestre(token) : Promise.resolve(null),
          proximasCitas(token, A_LA_VISTA),
          listarHabitos(token),
          listarNotas(token),
        ])
        if (cancelado) return
        setApuntes(lista)
        setResumen(totales)
        setTrimestre(tri)
        setCitas(proximas)
        setHabitos(misHabitos)
        setNotas(misNotas)
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
  }, [token, periodo, recargas, fallo])

  /** Ejecuta una acción y recarga; si el token cayó, devuelve a la entrada. */
  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      recargar()
    } catch (e) {
      fallo(e)
    }
  }

  const deHoy = habitos.filter((h) => h.toca_hoy)
  const hechosHoy = deHoy.filter((h) => h.hecho_hoy).length

  return (
    <>
      <Cabecera titulo={saludo()} subtitulo={fechaLarga(hoyISO)} />

      <Captura token={token} onCambio={recargar} onFallo={fallo} />

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <section className="bloque">
        <div className="bloque-cabecera">
          <h2>
            {periodo === 'dia'
              ? 'Resumen de hoy'
              : periodo === 'mes'
                ? `Resumen de ${MESES[new Date().getMonth()]}`
                : `Resumen del ${trimestre?.trimestre ?? ''}º trimestre`}
          </h2>
          <Segmentado opciones={PERIODOS} valor={periodo} onCambio={setPeriodo} etiqueta="Periodo" />
        </div>

        {periodo === 'trimestre' && trimestre ? (
          <dl className="kpis cuatro">
            <Kpi nombre="Cobrado" valor={euros(trimestre.cobrado)} tipo="cobrado" />
            <Kpi nombre="Gastos" valor={euros(trimestre.gastos)} tipo="gasto" />
            <Kpi nombre="Neto" valor={euros(trimestre.neto)} tipo="neto" />
            <Kpi
              nombre="Modelo 130 aprox."
              valor={euros(trimestre.estimacion_130)}
              nota="20 % del neto. Orientativo: confírmalo con tu gestor."
            />
          </dl>
        ) : (
          <dl className="kpis cuatro">
            <Kpi nombre="Cobrado" valor={resumen ? euros(resumen.cobrado) : '—'} tipo="cobrado" />
            <Kpi nombre="Pendiente" valor={resumen ? euros(resumen.pendiente) : '—'} tipo="pendiente" />
            <Kpi nombre="Gastos" valor={resumen ? euros(resumen.gastos) : '—'} tipo="gasto" />
            <Kpi nombre="Neto" valor={resumen ? euros(resumen.neto) : '—'} tipo="neto" />
          </dl>
        )}
      </section>

      <div className="rejilla-inicio">
        {/* Dos columnas y no una rejilla: cada tarjeta mide lo que mide su
            lista, y en rejilla la más corta dejaba un hueco debajo. */}
        <div>
          <section className="tarjeta">
            <div className="tarjeta-cabecera">
              <h2>
                <Wallet size={18} />
                Movimientos de hoy
              </h2>
              <button className="enlace" onClick={() => onIr('finanzas')}>
                Finanzas <ChevronRight size={15} />
              </button>
            </div>
            {cargando ? (
              <Esqueleto />
            ) : apuntes.length === 0 ? (
              <Vacio titulo="Aún no has anotado nada hoy">
                Escribe arriba un trabajo o un gasto, o escanea un ticket.
              </Vacio>
            ) : (
              <ul className="lista">
                {apuntes.map((a) => (
                  <FilaMovimiento
                    key={a.id}
                    apunte={a}
                    onAbrir={a.tipo === 'nota' ? undefined : () => setEditando(a)}
                    onCobrar={() => void accion(() => marcarCobrado(token, a.id))}
                    onTicket={() => void accion(() => abrirFactura(token, a.factura_id!))}
                  />
                ))}
              </ul>
            )}
          </section>

          <section className="tarjeta">
            <div className="tarjeta-cabecera">
              <h2>
                <Flame size={18} />
                Hábitos de hoy
                {deHoy.length > 0 && (
                  <span className="contador">
                    {hechosHoy}/{deHoy.length}
                  </span>
                )}
              </h2>
              <button className="enlace" onClick={() => onIr('habitos')}>
                Hábitos <ChevronRight size={15} />
              </button>
            </div>
            {cargando ? (
              <Esqueleto />
            ) : habitos.length === 0 ? (
              <Vacio titulo="Todavía no tienes hábitos">
                <button className="boton suave pequeno" onClick={() => onIr('habitos')}>
                  Crear el primero
                </button>
              </Vacio>
            ) : deHoy.length === 0 ? (
              <Vacio titulo="Hoy no toca ninguno">Día libre: la racha no se rompe.</Vacio>
            ) : (
              <>
                <div
                  className="progreso"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={deHoy.length}
                  aria-valuenow={hechosHoy}
                >
                  <i style={{ width: `${(hechosHoy / deHoy.length) * 100}%` }} />
                </div>
                <ul className="lista">
                  {deHoy.map((h) => (
                    <li key={h.habito.id} className={h.hecho_hoy ? 'fila hecha' : 'fila'}>
                      <button
                        className={h.hecho_hoy ? 'marca puesta' : 'marca'}
                        aria-pressed={h.hecho_hoy}
                        aria-label={h.habito.nombre}
                        onClick={() =>
                          void accion(() =>
                            marcarDiaHabito(token, h.habito.id, hoyISO, !h.hecho_hoy),
                          )
                        }
                      >
                        <Check size={14} strokeWidth={3} />
                      </button>
                      <span className="principal">{h.habito.nombre}</span>
                      {h.racha > 0 && (
                        <span className="racha" title="Días seguidos">
                          <Flame size={14} />
                          {h.racha}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

        </div>
        <div>
          <section className="tarjeta">
            <div className="tarjeta-cabecera">
              <h2>
                <CalendarDays size={18} />
                Próximas citas
              </h2>
              <button className="enlace" onClick={() => onIr('agenda')}>
                Agenda <ChevronRight size={15} />
              </button>
            </div>
            {cargando ? (
              <Esqueleto />
            ) : citas.length === 0 ? (
              <Vacio titulo="Nada en la agenda">
                <button className="boton suave pequeno" onClick={() => onIr('agenda')}>
                  Añadir una cita
                </button>
              </Vacio>
            ) : (
              <ul className="lista">
                {citas.map((c) => (
                  <li
                    key={c.id}
                    className="fila tocable"
                    onClick={() => onIr('agenda', c.fecha < hoyISO ? hoyISO : c.fecha)}
                  >
                    <button
                      className="marca"
                      aria-label={`Marcar «${c.titulo}» como hecha`}
                      title="Marcar como hecha"
                      onClick={(e) => {
                        e.stopPropagation()
                        void accion(() => marcarCitaHecha(token, c.id))
                      }}
                    >
                      <Check size={14} strokeWidth={3} />
                    </button>
                    <span className="principal">
                      {c.titulo}
                      {(c.cliente || c.direccion) && (
                        <small>{[c.cliente?.nombre, c.direccion].filter(Boolean).join(' · ')}</small>
                      )}
                    </span>
                    <span className={c.fecha <= hoyISO ? 'pastilla acento' : 'pastilla'}>
                      {/* Una reforma que empezó ayer sigue siendo cosa de hoy. */}
                      {c.fecha < hoyISO ? 'En curso' : diaRelativo(c.fecha)}
                      {hhmm(c.hora) ? ` · ${hhmm(c.hora)}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="tarjeta">
            <div className="tarjeta-cabecera">
              <h2>
                <StickyNote size={18} />
                Notas pendientes
                {notas.length > 0 && <span className="contador">{notas.length}</span>}
              </h2>
              <button className="enlace" onClick={() => onIr('notas')}>
                Notas <ChevronRight size={15} />
              </button>
            </div>
            {cargando ? (
              <Esqueleto />
            ) : notas.length === 0 ? (
              <Vacio titulo="El buzón está vacío">
                Lo que anotes sin importe cae aquí hasta que le pongas fecha.
              </Vacio>
            ) : (
              <>
                <ul className="lista">
                  {notas.slice(0, A_LA_VISTA).map((n) => (
                    <li key={n.id} className="fila">
                      <button
                        className="marca"
                        aria-label={`Marcar «${n.concepto}» como hecha`}
                        title="Marcar como hecha"
                        onClick={() => void accion(() => marcarNotaHecha(token, n.id))}
                      >
                        <Check size={14} strokeWidth={3} />
                      </button>
                      <span className="principal">
                        {n.concepto}
                        {n.cliente && <small>{n.cliente.nombre}</small>}
                      </span>
                    </li>
                  ))}
                </ul>
                {notas.length > A_LA_VISTA && (
                  <button className="enlace gris mas" onClick={() => onIr('notas')}>
                    y {notas.length - A_LA_VISTA} más
                  </button>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {editando && (
        <EditorMovimiento
          token={token}
          apunte={editando}
          onCambio={recargar}
          onCerrar={() => setEditando(null)}
        />
      )}
    </>
  )
}
