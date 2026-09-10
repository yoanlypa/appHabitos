/**
 * El buzón: lo apuntado que todavía no tiene ni fecha ni precio.
 *
 * Aquí cae lo que se dicta al bot sin importe ("quiero revisar el coche") y
 * lo que se escribe a mano. Mientras no tenga fecha, es una nota; en cuanto
 * se le pone una, deja de estar aquí y aparece en la agenda. Por eso el
 * buzón solo enseña lo que sigue sin fecha: si se quedara todo, a la tercera
 * semana dejaría de mirarse.
 *
 * Editar se hace en la propia línea, sin modal: cambiar una palabra es lo
 * más frecuente y no merece abrir una ventana. El modal se guarda para
 * agendar, que es donde hay varias decisiones a la vez (qué días, a qué
 * hora, y con qué texto se va a quedar).
 *
 * Lo cumplido se marca, no se borra: sale de la lista pero se puede abrir
 * abajo y devolver al buzón. Borrar es para lo que se apuntó mal, y son dos
 * cosas distintas que no pueden compartir botón.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  agendarNota,
  borrarNota,
  crearNota,
  editarNota,
  listarNotas,
  marcarNotaHecha,
  TokenInvalido,
  type Nota,
} from '../api'
import { fechaCorta, iso } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
  /** Para saltar a la agenda después de agendar algo, y verlo ya puesto. */
  onAgendada?: (fecha: string) => void
}

export function Notas({ token, onTokenInvalido, onAgendada }: Props) {
  const [notas, setNotas] = useState<Nota[]>([])
  const [texto, setTexto] = useState('')
  const [editando, setEditando] = useState<number | null>(null)
  const [borrador, setBorrador] = useState('')
  const [agendando, setAgendando] = useState<Nota | null>(null)
  const [hechas, setHechas] = useState<Nota[]>([])
  const [verHechas, setVerHechas] = useState(false)
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
        // Las hechas solo se piden si se van a enseñar: son las que crecen.
        const [lista, cumplidas] = await Promise.all([
          listarNotas(token),
          verHechas ? listarNotas(token, true) : Promise.resolve([]),
        ])
        if (cancelado) return
        setNotas(lista)
        setHechas(cumplidas)
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

  return (
    <section className="apuntes buzon">
      <h2>Buzón de notas</h2>

      <form className="alta" onSubmit={apuntar}>
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Revisar el coche"
          aria-label="Nueva nota"
        />
        <button type="submit" disabled={!texto.trim()}>
          Añadir
        </button>
      </form>
      <p className="ayuda">
        Aquí no se apunta dinero: lo que escribas se guarda tal cual. Ponle fecha y pasa a la
        agenda.
      </p>

      {error && <p className="error">{error}</p>}

      {cargando ? (
        <p className="vacio">Cargando…</p>
      ) : notas.length === 0 ? (
        <p className="vacio">No tienes nada pendiente sin fecha.</p>
      ) : (
        <ul className="notas">
          {notas.map((n) => (
            <li key={n.id}>
              {editando === n.id ? (
                <input
                  className="editando"
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
                <span className="concepto">
                  {n.concepto}
                  <small>
                    {fechaCorta(n.fecha)}
                    {n.cliente ? ` · ${n.cliente.nombre}` : ''}
                    {n.origen === 'bot' ? ' · por Telegram' : ''}
                  </small>
                </span>
              )}

              <div className="acciones">
                <button
                  className="mini hecha"
                  title="Marcar como hecha"
                  onClick={() => void accion(() => marcarNotaHecha(token, n.id))}
                >
                  ✓
                </button>
                <button className="mini" title="Ponerle fecha" onClick={() => setAgendando(n)}>
                  Agendar
                </button>
                <button className="mini" title="Editar" onClick={() => empezarAEditar(n)}>
                  ✎
                </button>
                <button
                  className="mini borrar"
                  title="Borrar"
                  onClick={() => {
                    if (confirm(`¿Borrar «${n.concepto}»?`)) {
                      void accion(() => borrarNota(token, n.id))
                    }
                  }}
                >
                  ✕
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="titulo-fila">
        <button className="enlace" onClick={() => setVerHechas((v) => !v)}>
          {verHechas ? 'Ocultar lo hecho' : 'Ver lo hecho'}
        </button>
      </div>

      {verHechas &&
        (hechas.length === 0 ? (
          <p className="vacio">Todavía no has marcado nada como hecho.</p>
        ) : (
          <ul className="notas cumplidas">
            {hechas.map((n) => (
              <li key={n.id}>
                <span className="concepto">
                  {n.concepto}
                  <small>{fechaCorta(n.fecha)}</small>
                </span>
                <div className="acciones">
                  <button
                    className="mini"
                    title="Devolver al buzón"
                    onClick={() => void accion(() => marcarNotaHecha(token, n.id, false))}
                  >
                    ↩
                  </button>
                  <button
                    className="mini borrar"
                    title="Borrar"
                    onClick={() => {
                      if (confirm(`¿Borrar «${n.concepto}»?`)) {
                        void accion(() => borrarNota(token, n.id))
                      }
                    }}
                  >
                    ✕
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ))}

      {agendando && (
        <ModalAgendar
          nota={agendando}
          onCerrar={() => setAgendando(null)}
          onGuardar={async (datos) => {
            await accion(async () => {
              await agendarNota(token, agendando.id, datos)
              setAgendando(null)
              onAgendada?.(datos.fecha)
            })
          }}
        />
      )}
    </section>
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
    <div className="modal-fondo" role="dialog" aria-modal="true" aria-label="Poner fecha">
      <form className="modal" onSubmit={enviar}>
        <h3>Poner fecha</h3>

        <label>
          Tarea
          <input value={titulo} onChange={(e) => setTitulo(e.target.value)} autoFocus />
        </label>

        <label>
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
          <label>
            Hasta
            <input
              type="date"
              value={hasta}
              min={desde}
              onChange={(e) => setHasta(e.target.value)}
            />
          </label>
        )}

        <label>
          Hora <small>(opcional)</small>
          <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
        </label>

        {!finValido && <p className="error">El último día no puede ser antes del primero.</p>}

        <div className="botones">
          <button type="button" className="enlace" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" disabled={!titulo.trim() || !finValido}>
            Pasar a la agenda
          </button>
        </div>
      </form>
    </div>
  )
}
