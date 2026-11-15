/**
 * La ficha de un trabajo, como una página de Notion.
 *
 * Arriba el nombre en grande y las propiedades (cliente, fechas, facturado,
 * reseña), que se cambian ahí mismo: tocar y listo, sin botón de guardar.
 * Debajo, las cuentas del trabajo y lo que tiene dentro: cobros y gastos,
 * notas y citas, cada cosa con su botón para añadir.
 *
 * Todo lo de dentro son las mismas filas que en el resto de la app (un gasto
 * de aquí sale en Finanzas, una cita en la agenda): la ficha solo las junta.
 * Las cuentas las hace el backend.
 */
import {
  ArrowLeft,
  BadgeCheck,
  Calendar,
  CalendarCheck,
  Check,
  Plus,
  Star,
  StickyNote,
  Trash2,
  User,
  Wallet,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import {
  abrirFactura,
  borrarCita,
  borrarNota,
  borrarTrabajo,
  crearCita,
  crearNota,
  editarCita,
  editarTrabajo,
  fichaDeTrabajo,
  listarClientes,
  marcarCitaHecha,
  marcarCobrado,
  marcarNotaHecha,
  TokenInvalido,
  type Apunte,
  type Cita,
  type ClienteListado,
  type DatosTrabajo,
  type FichaDeTrabajo,
} from '../api'
import { avisar, confirmar } from '../ui/avisos'
import { ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { diaRelativo, euros, fechaCorta, hhmm, iso, terminado } from '../utiles'
import { FormCita, type DatosCita } from './Agenda'
import { EditorMovimiento } from './EditorMovimiento'
import { FilaMovimiento } from './FilaMovimiento'

type Props = {
  token: string
  trabajoId: number
  onTokenInvalido: () => void
  onVolver: () => void
}

/** Lo que hay abierto encima de la ficha. */
type Ventana =
  | { tipo: 'movimiento'; apunte: Apunte | null; nuevo?: 'trabajo' | 'gasto' }
  | { tipo: 'cita'; cita: Cita | null }

export function FichaTrabajo({ token, trabajoId, onTokenInvalido, onVolver }: Props) {
  const [ficha, setFicha] = useState<FichaDeTrabajo | null>(null)
  const [clientes, setClientes] = useState<ClienteListado[]>([])
  const [titulo, setTitulo] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [nota, setNota] = useState('')
  const [ventana, setVentana] = useState<Ventana | null>(null)
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')
  const tituloRef = useRef<HTMLTextAreaElement>(null)
  const leida = useRef(false)

  // El nombre crece en varias líneas en vez de cortarse: un textarea a la
  // medida de su texto (el CSS de "ajustar al contenido" aún no va en iPhone).
  useLayoutEffect(() => {
    const caja = tituloRef.current
    if (!caja) return
    caja.style.height = 'auto'
    caja.style.height = `${caja.scrollHeight}px`
  }, [titulo, ficha])

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
    fichaDeTrabajo(token, trabajoId)
      .then((f) => {
        if (cancelado) return
        // El nombre y la descripción se leen solo la primera vez: al recargar
        // por otro cambio, pisarían lo que se está escribiendo en ese momento.
        if (!leida.current) {
          leida.current = true
          setTitulo(f.trabajo.titulo)
          setDescripcion(f.trabajo.descripcion ?? '')
        }
        setFicha(f)
        setError('')
      })
      .catch((e) => {
        if (!cancelado) fallo(e)
      })
    return () => {
      cancelado = true
    }
  }, [token, trabajoId, recargas, fallo])

  useEffect(() => {
    listarClientes(token)
      .then(setClientes)
      .catch(() => {})
  }, [token])

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      recargar()
    } catch (e) {
      fallo(e)
    }
  }

  /** Cambia una propiedad del trabajo al momento, como en Notion. */
  function cambiar(cambios: Partial<DatosTrabajo>) {
    void accion(() => editarTrabajo(token, trabajoId, cambios))
  }

  if (!ficha) {
    return error ? (
      <>
        <button className="enlace gris volver" onClick={onVolver}>
          <ArrowLeft size={16} /> Trabajos
        </button>
        <ErrorEnLinea>{error}</ErrorEnLinea>
      </>
    ) : (
      <Esqueleto />
    )
  }

  const { trabajo: t, cuentas } = ficha
  const notasPendientes = ficha.notas.filter((n) => !n.hecha)
  const notasHechas = ficha.notas.filter((n) => n.hecha)

  async function borrar() {
    const dentro = ficha!.movimientos.length + ficha!.notas.length + ficha!.citas.length
    const si = await confirmar({
      titulo: `¿Borrar «${t.titulo}»?`,
      texto:
        dentro > 0
          ? `Se borra la ficha, no lo que tiene dentro: sus ${dentro} cobros, gastos, notas y citas se quedan sueltos en la app.`
          : 'No tiene nada dentro. No se puede deshacer.',
      aceptar: 'Borrar trabajo',
      peligro: true,
    })
    if (!si) return
    try {
      await borrarTrabajo(token, t.id)
      avisar(`Trabajo borrado · ${t.titulo}`)
      onVolver()
    } catch (e) {
      fallo(e)
    }
  }

  async function guardarCita(datos: DatosCita, cita: Cita | null) {
    if (cita) await editarCita(token, cita.id, datos)
    else await crearCita(token, { ...datos, trabajo_id: t.id })
    setVentana(null)
    recargar()
  }

  function apuntarNota(e: React.FormEvent) {
    e.preventDefault()
    const limpio = nota.trim()
    if (!limpio) return
    void accion(async () => {
      await crearNota(token, limpio, t.id)
      setNota('')
    })
  }

  return (
    <div className="pagina-notion">
      <div className="pagina-arriba">
        <button className="enlace gris volver" onClick={onVolver}>
          <ArrowLeft size={16} /> Trabajos
        </button>
        <button
          className="boton-icono peligro"
          onClick={() => void borrar()}
          aria-label="Borrar trabajo"
          title="Borrar trabajo"
        >
          <Trash2 size={18} />
        </button>
      </div>

      <textarea
        ref={tituloRef}
        className="titulo-pagina"
        rows={1}
        value={titulo}
        aria-label="Nombre del trabajo"
        placeholder="Sin nombre"
        onChange={(e) => setTitulo(e.target.value.replace(/\n/g, ' '))}
        onBlur={() => {
          const limpio = titulo.trim()
          if (!limpio) setTitulo(t.titulo)
          else if (limpio !== t.titulo) cambiar({ titulo: limpio })
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            ;(e.target as HTMLTextAreaElement).blur()
          }
        }}
      />

      <dl className="propiedades">
        <Propiedad icono={User} nombre="Cliente">
          <select
            value={t.cliente_id ?? ''}
            onChange={(e) => cambiar({ cliente_id: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">Sin cliente</option>
            {clientes.map((c) => (
              <option key={c.cliente.id} value={c.cliente.id}>
                {c.cliente.nombre}
              </option>
            ))}
          </select>
        </Propiedad>
        <Propiedad icono={Calendar} nombre="Empieza">
          <input
            type="date"
            value={t.fecha_inicio ?? ''}
            onChange={(e) => cambiar({ fecha_inicio: e.target.value || null })}
          />
        </Propiedad>
        <Propiedad icono={CalendarCheck} nombre="Termina">
          <input
            type="date"
            value={t.fecha_fin ?? ''}
            min={t.fecha_inicio ?? undefined}
            onChange={(e) => cambiar({ fecha_fin: e.target.value || null })}
          />
          {terminado(t.fecha_fin) && <span className="pastilla">Terminado</span>}
        </Propiedad>
        <Propiedad icono={BadgeCheck} nombre="Facturado">
          <Interruptor
            activo={t.facturado}
            onCambio={(v) => cambiar({ facturado: v })}
            si="Lo facturo yo · va a la gestoría"
            no="No lo facturo yo · no va a la gestoría"
          />
        </Propiedad>
        <Propiedad icono={Star} nombre="Reseña">
          <Interruptor
            activo={t.resena}
            onCambio={(v) => cambiar({ resena: v })}
            si="El cliente dejó reseña"
            no={terminado(t.fecha_fin) ? 'Todavía no · pídesela' : 'Todavía no'}
          />
        </Propiedad>
      </dl>

      <textarea
        className="descripcion-pagina"
        value={descripcion}
        rows={2}
        placeholder="Añade una descripción: qué hay que hacer, medidas, materiales…"
        aria-label="Descripción"
        onChange={(e) => setDescripcion(e.target.value)}
        onBlur={() => {
          if (descripcion.trim() !== (t.descripcion ?? '')) cambiar({ descripcion: descripcion })
        }}
      />

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <dl className="kpis cuatro">
        <Kpi nombre="Cobrado" valor={euros(cuentas.cobrado)} tipo="cobrado" />
        <Kpi nombre="Por cobrar" valor={euros(cuentas.pendiente)} tipo="pendiente" />
        <Kpi nombre="Gastos" valor={euros(cuentas.gastos)} tipo="gasto" />
        <Kpi nombre="Te queda" valor={euros(cuentas.beneficio)} tipo="neto" nota="Ingresos menos gastos" />
      </dl>

      <Bloque
        icono={Wallet}
        titulo="Ingresos y gastos"
        cuenta={ficha.movimientos.length}
        acciones={
          <>
            <button
              className="boton suave pequeno"
              onClick={() => setVentana({ tipo: 'movimiento', apunte: null, nuevo: 'trabajo' })}
            >
              <Plus size={15} /> Cobro
            </button>
            <button
              className="boton suave pequeno"
              onClick={() => setVentana({ tipo: 'movimiento', apunte: null, nuevo: 'gasto' })}
            >
              <Plus size={15} /> Gasto
            </button>
          </>
        }
      >
        {ficha.movimientos.length === 0 ? (
          <Vacio>Añade lo que cobras y lo que gastas en esta obra.</Vacio>
        ) : (
          <ul className="lista">
            {ficha.movimientos.map((a) => (
              <FilaMovimiento
                key={a.id}
                apunte={a}
                detalle={`${fechaCorta(a.fecha)} · ${
                  a.tipo === 'gasto' ? 'gasto' : a.pendiente ? 'por cobrar' : 'cobrado'
                }`}
                onAbrir={() => setVentana({ tipo: 'movimiento', apunte: a })}
                onCobrar={() => void accion(() => marcarCobrado(token, a.id))}
                onTicket={() => void accion(() => abrirFactura(token, a.factura_id!))}
              />
            ))}
          </ul>
        )}
      </Bloque>

      <Bloque icono={StickyNote} titulo="Notas" cuenta={notasPendientes.length}>
        <form className="nueva-tarjeta" onSubmit={apuntarNota}>
          <Plus size={18} />
          <input
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Añadir una nota: comprar silicona, medir ventana…"
            aria-label="Nueva nota"
            enterKeyHint="done"
          />
          {nota.trim() && (
            <button type="submit" className="boton pequeno">
              Añadir
            </button>
          )}
        </form>
        {ficha.notas.length > 0 && (
          <ul className="lista">
            {[...notasPendientes, ...notasHechas].map((n) => (
              <li key={n.id} className={n.hecha ? 'fila hecha' : 'fila'}>
                <button
                  className={n.hecha ? 'marca puesta' : 'marca'}
                  aria-pressed={n.hecha}
                  aria-label={n.hecha ? 'Devolver a pendiente' : 'Marcar como hecha'}
                  onClick={() => void accion(() => marcarNotaHecha(token, n.id, !n.hecha))}
                >
                  <Check size={14} strokeWidth={3} />
                </button>
                <span className="principal">
                  {n.concepto}
                  <small>{fechaCorta(n.fecha)}</small>
                </span>
                <button
                  className="boton-icono peligro"
                  aria-label="Borrar nota"
                  title="Borrar nota"
                  onClick={async () => {
                    const si = await confirmar({
                      titulo: `¿Borrar «${n.concepto}»?`,
                      texto: 'Si ya la has hecho, mejor márcala: así queda constancia.',
                      aceptar: 'Borrar',
                      peligro: true,
                    })
                    if (si) void accion(() => borrarNota(token, n.id))
                  }}
                >
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Bloque>

      <Bloque
        icono={Calendar}
        titulo="Citas y recordatorios"
        cuenta={ficha.citas.filter((c) => !c.hecha).length}
        acciones={
          <button
            className="boton suave pequeno"
            onClick={() => setVentana({ tipo: 'cita', cita: null })}
          >
            <Plus size={15} /> Cita
          </button>
        }
      >
        {ficha.citas.length === 0 ? (
          <Vacio>
            Pon aquí las visitas y entregas de esta obra. Te aviso por Telegram y por correo.
          </Vacio>
        ) : (
          <ul className="lista">
            {ficha.citas.map((c) => (
              <li
                key={c.id}
                className={c.hecha ? 'fila tocable hecha' : 'fila tocable'}
                onClick={() => setVentana({ tipo: 'cita', cita: c })}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.target === e.currentTarget)
                    setVentana({ tipo: 'cita', cita: c })
                }}
              >
                <button
                  className={c.hecha ? 'marca puesta' : 'marca'}
                  aria-pressed={c.hecha}
                  aria-label={c.hecha ? 'Marcar como pendiente' : 'Marcar como hecha'}
                  onClick={(e) => {
                    e.stopPropagation()
                    void accion(() => marcarCitaHecha(token, c.id, !c.hecha))
                  }}
                >
                  <Check size={14} strokeWidth={3} />
                </button>
                <span className="principal">
                  {c.titulo}
                  {c.direccion && <small>{c.direccion}</small>}
                </span>
                <span className={c.fecha <= iso(new Date()) && !c.hecha ? 'pastilla acento' : 'pastilla'}>
                  {diaRelativo(c.fecha)}
                  {hhmm(c.hora) ? ` · ${hhmm(c.hora)}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Bloque>

      {ventana?.tipo === 'movimiento' && (
        <EditorMovimiento
          token={token}
          apunte={ventana.apunte}
          tipoInicial={ventana.nuevo}
          trabajoInicial={t.id}
          onCambio={recargar}
          onCerrar={() => setVentana(null)}
        />
      )}
      {ventana?.tipo === 'cita' && (
        <FormCita
          cita={ventana.cita}
          dia={iso(new Date())}
          clientes={clientes}
          clienteInicial={t.cliente_id}
          onGuardar={(datos) => guardarCita(datos, ventana.cita)}
          onBorrar={
            ventana.cita
              ? async () => {
                  await borrarCita(token, ventana.cita!.id)
                  setVentana(null)
                  recargar()
                }
              : undefined
          }
          onCerrar={() => setVentana(null)}
        />
      )}
    </div>
  )
}

/** Una fila de propiedades: icono, nombre y el control que la cambia. */
function Propiedad({
  icono: Icono,
  nombre,
  children,
}: {
  icono: LucideIcon
  nombre: string
  children: ReactNode
}) {
  return (
    <div className="propiedad">
      <dt>
        <Icono size={16} />
        {nombre}
      </dt>
      <dd>{children}</dd>
    </div>
  )
}

/** Un sí/no que se cambia de un toque, con lo que significa escrito al lado. */
function Interruptor({
  activo,
  onCambio,
  si,
  no,
}: {
  activo: boolean
  onCambio: (valor: boolean) => void
  si: string
  no: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activo}
      className={activo ? 'interruptor activo' : 'interruptor'}
      onClick={() => onCambio(!activo)}
    >
      <i aria-hidden="true" />
      <span>{activo ? si : no}</span>
    </button>
  )
}

/** Una sección de la página: título con su icono, cuántos hay y sus botones. */
function Bloque({
  icono: Icono,
  titulo,
  cuenta,
  acciones,
  children,
}: {
  icono: LucideIcon
  titulo: string
  cuenta: number
  acciones?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="tarjeta bloque-pagina">
      <div className="tarjeta-cabecera">
        <h2>
          <Icono size={18} />
          {titulo}
          {cuenta > 0 && <span className="contador">{cuenta}</span>}
        </h2>
        {acciones && <div className="bloque-acciones">{acciones}</div>}
      </div>
      {children}
    </section>
  )
}
