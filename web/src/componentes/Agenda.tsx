/**
 * La agenda: calendario del mes y las citas del día elegido.
 *
 * El calendario no es decoración: de un vistazo tienes que ver qué días
 * tienes ocupados, que es la pregunta del domingo por la noche. En el
 * ordenador cada día enseña sus citas dentro de la casilla, como en un
 * calendario de pared; en el móvil no caben y llevan un punto.
 *
 * Tocar una cita la abre para corregirla (el texto, el día, la hora, el
 * cliente). Borrar va dentro de esa ventana y con confirmación, igual que en
 * los movimientos: en una lista se toca sin querer.
 */
import { CalendarDays, Check, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  borrarCita,
  citasDelDia,
  citasDelMes,
  crearCita,
  editarCita,
  listarClientes,
  marcarCitaHecha,
  TokenInvalido,
  type Cita,
  type ClienteListado,
} from '../api'
import { confirmar } from '../ui/avisos'
import { Calendario } from '../ui/Calendario'
import { Modal } from '../ui/Modal'
import { Cabecera, ErrorEnLinea, Vacio } from '../ui/piezas'
import { diaRelativo, diasDelRango, fechaCorta, fechaLarga, hhmm, iso } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
  /** El día que se enseña al llegar (al agendar una nota, el suyo). */
  diaInicial?: string
}

/** Cuántas citas caben escritas en una casilla antes de poner "+2". */
const EN_CASILLA = 2

export function Agenda({ token, onTokenInvalido, diaInicial }: Props) {
  const hoyISO = iso(new Date())
  const primero = diaInicial ?? hoyISO
  const [anio, setAnio] = useState(Number(primero.slice(0, 4)))
  const [mes, setMes] = useState(Number(primero.slice(5, 7)))
  const [diaElegido, setDiaElegido] = useState(primero)
  const [delMes, setDelMes] = useState<Cita[]>([])
  const [delDia, setDelDia] = useState<Cita[]>([])
  const [clientes, setClientes] = useState<ClienteListado[]>([])
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')
  // undefined: cerrado · null: una nueva · Cita: editar esa
  const [formulario, setFormulario] = useState<Cita | null | undefined>(undefined)

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
        const [mesCitas, diaCitas, cli] = await Promise.all([
          citasDelMes(token, anio, mes),
          citasDelDia(token, diaElegido),
          listarClientes(token),
        ])
        if (cancelado) return
        setDelMes(mesCitas)
        setDelDia(diaCitas)
        setClientes(cli)
        setError('')
      } catch (e) {
        if (!cancelado) fallo(e)
      }
    }
    void cargar()
    return () => {
      cancelado = true
    }
  }, [token, anio, mes, diaElegido, recargas, fallo])

  // Una cita de varios días sale en todos: si solo saliera en el primero, el
  // resto del rango parecería libre justo cuando no lo está.
  const porDia = new Map<string, Cita[]>()
  for (const c of delMes) {
    for (const dia of diasDelRango(c.fecha, c.fecha_fin)) {
      porDia.set(dia, [...(porDia.get(dia) ?? []), c])
    }
  }

  function elegirMes(nuevoAnio: number, nuevoMes: number) {
    setAnio(nuevoAnio)
    setMes(nuevoMes)
    // Al volver al mes de hoy con el botón, el día elegido vuelve a hoy.
    const hoy = new Date()
    if (nuevoAnio === hoy.getFullYear() && nuevoMes === hoy.getMonth() + 1) setDiaElegido(hoyISO)
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

  async function guardar(datos: DatosCita) {
    if (formulario) await editarCita(token, formulario.id, datos)
    else await crearCita(token, datos)
    setFormulario(undefined)
    // Si se ha movido de día, se va con ella: que se vea dónde ha quedado.
    setDiaElegido(datos.fecha)
    setAnio(Number(datos.fecha.slice(0, 4)))
    setMes(Number(datos.fecha.slice(5, 7)))
    setRecargas((n) => n + 1)
  }

  async function borrar() {
    if (!formulario) return
    await borrarCita(token, formulario.id)
    setFormulario(undefined)
    setRecargas((n) => n + 1)
  }

  return (
    <>
      <Cabecera titulo="Agenda">
        <button className="boton" onClick={() => setFormulario(null)}>
          <Plus size={18} />
          Nueva cita
        </button>
      </Cabecera>

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <div className="agenda">
        <div className="tarjeta">
          <Calendario
            grande
            anio={anio}
            mes={mes}
            onMes={elegirMes}
            onDia={setDiaElegido}
            celda={(fecha) => {
              const citas = porDia.get(fecha) ?? []
              return {
                clase: fecha === diaElegido ? 'elegido' : undefined,
                pulsado: fecha === diaElegido,
                etiqueta: `${fechaLarga(fecha)}${citas.length ? `, ${citas.length} ${citas.length === 1 ? 'cita' : 'citas'}` : ''}`,
                extra: citas.length > 0 && (
                  <>
                    <i className="punto" />
                    <span className="cal-citas">
                      {citas.slice(0, EN_CASILLA).map((c) => (
                        <span key={c.id} className={c.hecha ? 'cal-cita hecha' : 'cal-cita'}>
                          {hhmm(c.hora) && <b>{hhmm(c.hora)}</b>} {c.titulo}
                        </span>
                      ))}
                      {citas.length > EN_CASILLA && (
                        <span className="cal-mas">+{citas.length - EN_CASILLA} más</span>
                      )}
                    </span>
                  </>
                ),
              }
            }}
          />
        </div>

        <section className="tarjeta dia-elegido">
          <div className="tarjeta-cabecera">
            <div>
              <h2>{diaRelativo(diaElegido)}</h2>
              <p className="subtitulo">{fechaLarga(diaElegido)}</p>
            </div>
            <button
              className="boton-icono borde"
              onClick={() => setFormulario(null)}
              aria-label="Nueva cita este día"
              title="Nueva cita este día"
            >
              <Plus size={18} />
            </button>
          </div>

          {delDia.length === 0 ? (
            <Vacio icono={CalendarDays} titulo="Día libre">
              No hay nada apuntado.
            </Vacio>
          ) : (
            <ul className="lista">
              {delDia.map((c) => (
                <li
                  key={c.id}
                  className={c.hecha ? 'fila tocable cita hecha' : 'fila tocable cita'}
                  onClick={() => setFormulario(c)}
                  title="Tocar para editar"
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && e.target === e.currentTarget) setFormulario(c)
                  }}
                >
                  <button
                    className={c.hecha ? 'marca puesta' : 'marca'}
                    aria-pressed={c.hecha}
                    aria-label={c.hecha ? 'Marcar como pendiente' : 'Marcar como hecha'}
                    title={c.hecha ? 'Marcar como pendiente' : 'Marcar como hecha'}
                    onClick={(e) => {
                      e.stopPropagation()
                      void accion(() => marcarCitaHecha(token, c.id, !c.hecha))
                    }}
                  >
                    <Check size={14} strokeWidth={3} />
                  </button>
                  <span className="principal">
                    {c.titulo}
                    {(c.cliente || c.direccion || c.fecha_fin) && (
                      <small>
                        {[
                          c.fecha_fin
                            ? `${fechaCorta(c.fecha)} → ${fechaCorta(c.fecha_fin)}`
                            : null,
                          c.cliente?.nombre,
                          c.direccion,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </small>
                    )}
                  </span>
                  {hhmm(c.hora) && <span className="hora">{hhmm(c.hora)}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {formulario !== undefined && (
        <FormCita
          cita={formulario}
          dia={diaElegido}
          clientes={clientes}
          onGuardar={guardar}
          onBorrar={formulario ? borrar : undefined}
          onCerrar={() => setFormulario(undefined)}
        />
      )}
    </>
  )
}

type DatosCita = {
  titulo: string
  fecha: string
  fecha_fin: string | null
  hora: string | null
  direccion: string | null
  cliente_id: number | null
}

/** Una cita nueva o una ya puesta: el mismo formulario para las dos. */
function FormCita({
  cita,
  dia,
  clientes,
  onGuardar,
  onBorrar,
  onCerrar,
}: {
  cita: Cita | null
  dia: string
  clientes: ClienteListado[]
  onGuardar: (datos: DatosCita) => Promise<void>
  onBorrar?: () => Promise<void>
  onCerrar: () => void
}) {
  const [titulo, setTitulo] = useState(cita?.titulo ?? '')
  const [fecha, setFecha] = useState(cita?.fecha ?? dia)
  const [variosDias, setVariosDias] = useState(Boolean(cita?.fecha_fin))
  const [hasta, setHasta] = useState(cita?.fecha_fin ?? cita?.fecha ?? dia)
  const [hora, setHora] = useState(hhmm(cita?.hora ?? null) ?? '')
  const [cliente, setCliente] = useState(cita?.cliente_id ? String(cita.cliente_id) : '')
  const [direccion, setDireccion] = useState(cita?.direccion ?? '')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  const finValido = !variosDias || hasta >= fecha
  const valido = titulo.trim() !== '' && fecha !== '' && finValido

  async function hacer(accion: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await accion()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se ha podido guardar')
      setOcupado(false)
    }
  }

  function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (!valido) return
    void hacer(() =>
      onGuardar({
        titulo: titulo.trim(),
        fecha,
        fecha_fin: variosDias && hasta > fecha ? hasta : null,
        hora: hora || null,
        direccion: direccion.trim() || null,
        cliente_id: cliente ? Number(cliente) : null,
      }),
    )
  }

  async function borrar() {
    if (!onBorrar || !cita) return
    const si = await confirmar({
      titulo: `¿Borrar «${cita.titulo}»?`,
      texto: cita.fecha_fin
        ? 'Se borra de todos sus días. No se puede deshacer.'
        : 'No se puede deshacer.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (si) void hacer(onBorrar)
  }

  return (
    <Modal titulo={cita ? 'Editar cita' : 'Nueva cita'} onCerrar={onCerrar}>
      <form className="formulario" onSubmit={enviar}>
        <label className="campo">
          Qué hay que hacer
          <input
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            placeholder="Montar la cocina de Ana"
            autoFocus={!cita}
          />
        </label>

        <div className="dos-campos">
          <label className="campo">
            {variosDias ? 'Desde' : 'Día'}
            <input
              type="date"
              value={fecha}
              onChange={(e) => {
                setFecha(e.target.value)
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
              if (e.target.checked && hasta < fecha) setHasta(fecha)
            }}
          />
          Dura varios días
        </label>
        {variosDias && (
          <label className="campo">
            Hasta
            <input type="date" value={hasta} min={fecha} onChange={(e) => setHasta(e.target.value)} />
          </label>
        )}

        <label className="campo">
          Cliente
          <select value={cliente} onChange={(e) => setCliente(e.target.value)}>
            <option value="">Sin cliente</option>
            {clientes.map((c) => (
              <option key={c.cliente.id} value={c.cliente.id}>
                {c.cliente.nombre}
              </option>
            ))}
          </select>
        </label>

        <label className="campo">
          <span>
            Dirección <small>(opcional)</small>
          </span>
          <input value={direccion} onChange={(e) => setDireccion(e.target.value)} />
        </label>

        {!finValido && <ErrorEnLinea>El último día no puede ser antes del primero.</ErrorEnLinea>}
        <ErrorEnLinea>{error}</ErrorEnLinea>

        <div className="botones">
          {cita && onBorrar && (
            <button
              type="button"
              className="boton-icono peligro"
              onClick={() => void borrar()}
              disabled={ocupado}
              aria-label="Borrar"
              title="Borrar"
            >
              <Trash2 size={18} />
            </button>
          )}
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar} disabled={ocupado}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!valido || ocupado}>
              {ocupado ? 'Guardando…' : cita ? 'Guardar' : 'Guardar cita'}
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}
