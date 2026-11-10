/**
 * Notas, en tablero: lo que hay por hacer, lo que ya tiene fecha y lo hecho.
 *
 * - **Buzón**: lo apuntado que todavía no tiene ni fecha ni precio. Aquí cae
 *   lo que se dicta al bot sin importe ("quiero revisar el coche") y lo que
 *   se escribe a mano.
 * - **Con fecha**: lo que ya está en la agenda y queda por delante. En cuanto
 *   a una nota se le pone fecha deja de ser una nota y pasa aquí: si el buzón
 *   se quedara con todo, a la tercera semana dejaría de mirarse.
 * - **Hecho**: lo cumplido se marca, no se borra. Sale del buzón pero se
 *   puede devolver. Borrar es para lo que se apuntó mal, y son dos cosas
 *   distintas que no pueden compartir botón.
 *
 * En el ordenador las tres columnas se ven a la vez y las tarjetas se
 * arrastran de una a otra; en el móvil se ve una columna y se cambia con las
 * pestañas de arriba, que arrastrar con el pulgar es pelearse con el scroll.
 * Los botones de cada tarjeta hacen lo mismo que arrastrar, así que nada
 * depende de saber que se puede.
 *
 * Editar se hace en la propia tarjeta, sin ventana: cambiar una palabra es lo
 * más frecuente y no merece abrir nada. La ventana se guarda para agendar,
 * que es donde hay varias decisiones a la vez.
 */
import {
  CalendarPlus,
  Check,
  Inbox,
  Pencil,
  Plus,
  Send,
  Trash2,
  Undo2,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  agendarNota,
  borrarNota,
  crearNota,
  editarNota,
  listarNotas,
  marcarCitaHecha,
  marcarNotaHecha,
  proximasCitas,
  TokenInvalido,
  type Cita,
  type Nota,
} from '../api'
import type { Ir } from '../secciones'
import { avisar, confirmar } from '../ui/avisos'
import { useEscritorio } from '../ui/ganchos'
import { Modal } from '../ui/Modal'
import { Cabecera, ErrorEnLinea, Esqueleto, Vacio } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { diaRelativo, fechaCorta, hhmm, iso } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
  /** Para saltar a la agenda después de agendar algo, y verlo ya puesto. */
  onIr: Ir
}

type Columna = 'buzon' | 'fecha' | 'hecho'

/** Cuántas citas enseña la columna "Con fecha": las de más allá se ven en la agenda. */
const CITAS_A_LA_VISTA = 30

export function Notas({ token, onTokenInvalido, onIr }: Props) {
  const escritorio = useEscritorio()
  const hoyISO = iso(new Date())
  const [columna, setColumna] = useState<Columna>('buzon')
  const [notas, setNotas] = useState<Nota[]>([])
  const [citas, setCitas] = useState<Cita[]>([])
  const [hechas, setHechas] = useState<Nota[]>([])
  const [texto, setTexto] = useState('')
  const [editando, setEditando] = useState<number | null>(null)
  const [borrador, setBorrador] = useState('')
  const [agendando, setAgendando] = useState<Nota | null>(null)
  const [sobre, setSobre] = useState<Columna | null>(null)
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(true)

  // Las hechas solo se piden si se van a enseñar: son las que crecen.
  const verHechas = escritorio || columna === 'hecho'

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
        const [lista, proximas, cumplidas] = await Promise.all([
          listarNotas(token),
          proximasCitas(token, CITAS_A_LA_VISTA),
          verHechas ? listarNotas(token, true) : Promise.resolve(null),
        ])
        if (cancelado) return
        setNotas(lista)
        setCitas(proximas)
        if (cumplidas) setHechas(cumplidas)
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
  }, [token, recargas, verHechas, fallo])

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      fallo(e)
    }
  }

  async function apuntar(e: React.FormEvent) {
    e.preventDefault()
    if (!texto.trim()) return
    await accion(async () => {
      await crearNota(token, texto)
      setTexto('')
    })
  }

  function empezarAEditar(nota: Nota) {
    setEditando(nota.id)
    setBorrador(nota.concepto)
  }

  async function guardarEdicion(id: number) {
    const limpio = borrador.trim()
    // Sin cambios o en blanco: se cierra y ya está, no hay que ir al servidor.
    const original = notas.find((n) => n.id === id)?.concepto
    if (!limpio || limpio === original) {
      setEditando(null)
      return
    }
    await accion(async () => {
      await editarNota(token, id, limpio)
      setEditando(null)
    })
  }

  async function borrar(nota: Nota) {
    const si = await confirmar({
      titulo: `¿Borrar «${nota.concepto}»?`,
      texto: 'Si ya la has hecho, mejor márcala como hecha: así queda constancia.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (si) void accion(() => borrarNota(token, nota.id))
  }

  /** Soltar una tarjeta en una columna hace lo mismo que su botón. */
  function soltar(destino: Columna, dato: string) {
    setSobre(null)
    const [origen, idTexto] = dato.split(':')
    const id = Number(idTexto)
    if (origen === 'buzon') {
      const nota = notas.find((n) => n.id === id)
      if (!nota) return
      if (destino === 'hecho') void accion(() => marcarNotaHecha(token, id))
      if (destino === 'fecha') setAgendando(nota)
    }
    if (origen === 'hecho' && destino === 'buzon') {
      void accion(() => marcarNotaHecha(token, id, false))
    }
  }

  function zona(id: Columna) {
    return {
      className: sobre === id ? 'columna sobre' : 'columna',
      onDragOver: (e: React.DragEvent) => {
        e.preventDefault()
        setSobre(id)
      },
      onDragLeave: (e: React.DragEvent) => {
        // Solo al salir de la columna, no al pasar por encima de una tarjeta.
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setSobre(null)
      },
      onDrop: (e: React.DragEvent) => {
        e.preventDefault()
        soltar(id, e.dataTransfer.getData('text/plain'))
      },
    }
  }

  function arrastrable(origen: Columna, id: number) {
    return {
      draggable: escritorio && editando !== id,
      onDragStart: (e: React.DragEvent) => {
        e.dataTransfer.setData('text/plain', `${origen}:${id}`)
        e.dataTransfer.effectAllowed = 'move'
      },
      onDragEnd: () => setSobre(null),
    }
  }

  const pestanas = [
    { id: 'buzon', nombre: 'Buzón', cuenta: notas.length },
    { id: 'fecha', nombre: 'Con fecha', cuenta: citas.length },
    { id: 'hecho', nombre: 'Hecho' },
  ] as const

  const visible = (id: Columna) => escritorio || columna === id

  return (
    <>
      <Cabecera
        titulo="Notas"
        subtitulo="Lo que tienes por hacer. Ponle fecha y pasa a la agenda."
      />

      {!escritorio && (
        <Segmentado opciones={pestanas} valor={columna} onCambio={setColumna} ancho etiqueta="Columna" />
      )}

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <div className="tablero">
        {visible('buzon') && (
          <section {...zona('buzon')}>
            <TituloColumna icono={Inbox} nombre="Buzón" cuenta={notas.length} />

            <form className="nueva-tarjeta" onSubmit={apuntar}>
              <Plus size={18} />
              <input
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                placeholder="Añadir una nota…"
                aria-label="Nueva nota"
                enterKeyHint="done"
              />
              {texto.trim() && (
                <button type="submit" className="boton pequeno">
                  Añadir
                </button>
              )}
            </form>

            {cargando ? (
              <Esqueleto />
            ) : notas.length === 0 ? (
              <Vacio icono={Inbox} titulo="Nada pendiente sin fecha">
                Lo que le dictes al bot sin importe cae aquí.
              </Vacio>
            ) : (
              <ul className="tarjetas">
                {notas.map((n) => (
                  <li key={n.id} className="tarjeta-nota" {...arrastrable('buzon', n.id)}>
                    {editando === n.id ? (
                      <input
                        autoFocus
                        value={borrador}
                        aria-label="Texto de la nota"
                        onChange={(e) => setBorrador(e.target.value)}
                        onBlur={() => void guardarEdicion(n.id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void guardarEdicion(n.id)
                          if (e.key === 'Escape') setEditando(null)
                        }}
                      />
                    ) : (
                      <p className="texto" onDoubleClick={() => empezarAEditar(n)}>
                        {n.concepto}
                      </p>
                    )}
                    <div className="tarjeta-nota-pie">
                      <span className="meta">
                        {fechaCorta(n.fecha)}
                        {n.cliente ? ` · ${n.cliente.nombre}` : ''}
                        {n.origen === 'bot' && (
                          <span className="via" title="Apuntada por Telegram">
                            <Send size={11} /> Telegram
                          </span>
                        )}
                      </span>
                      <span className="acciones">
                        <button
                          className="boton-icono bien"
                          title="Marcar como hecha"
                          aria-label="Marcar como hecha"
                          onClick={() => void accion(() => marcarNotaHecha(token, n.id))}
                        >
                          <Check size={17} />
                        </button>
                        <button
                          className="boton-icono"
                          title="Ponerle fecha"
                          aria-label="Ponerle fecha"
                          onClick={() => setAgendando(n)}
                        >
                          <CalendarPlus size={17} />
                        </button>
                        <button
                          className="boton-icono"
                          title="Editar"
                          aria-label="Editar"
                          onClick={() => empezarAEditar(n)}
                        >
                          <Pencil size={16} />
                        </button>
                        <button
                          className="boton-icono peligro"
                          title="Borrar"
                          aria-label="Borrar"
                          onClick={() => void borrar(n)}
                        >
                          <Trash2 size={16} />
                        </button>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {visible('fecha') && (
          <section {...zona('fecha')}>
            <TituloColumna icono={CalendarPlus} nombre="Con fecha" cuenta={citas.length} />
            {cargando ? (
              <Esqueleto />
            ) : citas.length === 0 ? (
              <Vacio icono={CalendarPlus} titulo="Nada en la agenda">
                {escritorio
                  ? 'Arrastra aquí una nota para ponerle fecha.'
                  : 'Toca el calendario de una nota para ponerle fecha.'}
              </Vacio>
            ) : (
              <ul className="tarjetas">
                {citas.map((c) => (
                  <li
                    key={c.id}
                    className="tarjeta-nota tocable"
                    onClick={() => onIr('agenda', c.fecha < hoyISO ? hoyISO : c.fecha)}
                    title="Ver en la agenda"
                  >
                    <span className={c.fecha <= hoyISO ? 'pastilla acento' : 'pastilla'}>
                      {c.fecha < hoyISO ? 'En curso' : diaRelativo(c.fecha)}
                      {hhmm(c.hora) ? ` · ${hhmm(c.hora)}` : ''}
                      {c.fecha_fin ? ` → ${fechaCorta(c.fecha_fin)}` : ''}
                    </span>
                    <p className="texto">{c.titulo}</p>
                    <div className="tarjeta-nota-pie">
                      <span className="meta">
                        {[c.cliente?.nombre, c.direccion].filter(Boolean).join(' · ')}
                      </span>
                      <span className="acciones">
                        <button
                          className="boton-icono bien"
                          title="Marcar como hecha"
                          aria-label="Marcar como hecha"
                          onClick={(e) => {
                            e.stopPropagation()
                            void accion(async () => {
                              await marcarCitaHecha(token, c.id)
                              avisar(`Hecho · ${c.titulo}`)
                            })
                          }}
                        >
                          <Check size={17} />
                        </button>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {visible('hecho') && (
          <section {...zona('hecho')}>
            <TituloColumna icono={Check} nombre="Hecho" cuenta={hechas.length} />
            {cargando ? (
              <Esqueleto />
            ) : hechas.length === 0 ? (
              <Vacio icono={Check} titulo="Todavía nada">
                Lo que marques como hecho se queda aquí.
              </Vacio>
            ) : (
              <ul className="tarjetas">
                {hechas.map((n) => (
                  <li key={n.id} className="tarjeta-nota cumplida" {...arrastrable('hecho', n.id)}>
                    <p className="texto">{n.concepto}</p>
                    <div className="tarjeta-nota-pie">
                      <span className="meta">{fechaCorta(n.fecha)}</span>
                      <span className="acciones">
                        <button
                          className="boton-icono"
                          title="Devolver al buzón"
                          aria-label="Devolver al buzón"
                          onClick={() => void accion(() => marcarNotaHecha(token, n.id, false))}
                        >
                          <Undo2 size={16} />
                        </button>
                        <button
                          className="boton-icono peligro"
                          title="Borrar"
                          aria-label="Borrar"
                          onClick={() => void borrar(n)}
                        >
                          <Trash2 size={16} />
                        </button>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>

      {agendando && (
        <ModalAgendar
          nota={agendando}
          onCerrar={() => setAgendando(null)}
          onGuardar={async (datos) => {
            await accion(async () => {
              await agendarNota(token, agendando.id, datos)
              setAgendando(null)
              onIr('agenda', datos.fecha)
            })
          }}
        />
      )}
    </>
  )
}

function TituloColumna({
  icono: Icono,
  nombre,
  cuenta,
}: {
  icono: LucideIcon
  nombre: string
  cuenta: number
}) {
  return (
    <header className="columna-titulo">
      <Icono size={16} />
      <h2>{nombre}</h2>
      <span className="contador">{cuenta}</span>
    </header>
  )
}

type DatosAgenda = { fecha: string; fecha_fin: string | null; hora: string | null; titulo: string }

/**
 * Ponerle fecha a una nota, que es donde deja de ser una nota.
 *
 * El texto se puede retocar aquí a propósito: lo que se dicta con prisa
 * ("revisar coche") no siempre es lo que quieres leer en la agenda dentro de
 * dos semanas, y este es el momento en el que estás pensando en ello.
 */
function ModalAgendar({
  nota,
  onCerrar,
  onGuardar,
}: {
  nota: Nota
  onCerrar: () => void
  onGuardar: (datos: DatosAgenda) => Promise<void>
}) {
  const hoy = iso(new Date())
  const [titulo, setTitulo] = useState(nota.concepto)
  const [desde, setDesde] = useState(hoy)
  const [variosDias, setVariosDias] = useState(false)
  const [hasta, setHasta] = useState(hoy)
  const [hora, setHora] = useState('')

  // El fin nunca puede quedar antes del inicio: el backend lo rechaza, pero
  // es mejor que aquí no llegue ni a poder escribirse.
  const finValido = !variosDias || hasta >= desde

  function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (!titulo.trim() || !finValido) return
    void onGuardar({
      fecha: desde,
      fecha_fin: variosDias && hasta !== desde ? hasta : null,
      hora: hora || null,
      titulo: titulo.trim(),
    })
  }

  return (
    <Modal titulo="Poner fecha" onCerrar={onCerrar}>
      <form className="formulario" onSubmit={enviar}>
        <label className="campo">
          Tarea
          <input value={titulo} onChange={(e) => setTitulo(e.target.value)} autoFocus />
        </label>

        <div className="dos-campos">
          <label className="campo">
            {variosDias ? 'Desde' : 'Día'}
            <input
              type="date"
              value={desde}
              onChange={(e) => {
                setDesde(e.target.value)
                if (hasta < e.target.value) setHasta(e.target.value)
              }}
            />
          </label>
          <label className="campo">
            <span>
              Hora <small>(opcional)</small>
            </span>
            <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
          </label>
        </div>

        <label className="casilla">
          <input
            type="checkbox"
            checked={variosDias}
            onChange={(e) => {
              setVariosDias(e.target.checked)
              if (e.target.checked && hasta < desde) setHasta(desde)
            }}
          />
          Dura varios días
        </label>

        {variosDias && (
          <label className="campo">
            Hasta
            <input
              type="date"
              value={hasta}
              min={desde}
              onChange={(e) => setHasta(e.target.value)}
            />
          </label>
        )}

        {!finValido && <ErrorEnLinea>El último día no puede ser antes del primero.</ErrorEnLinea>}

        <div className="botones">
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!titulo.trim() || !finValido}>
              Pasar a la agenda
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}
