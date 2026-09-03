/**
 * La agenda: calendario del mes y las citas del día elegido.
 *
 * El calendario no es decoración: de un vistazo tienes que ver qué días
 * tienes ocupados, que es la pregunta del domingo por la noche. Por eso los
 * días con cita llevan un punto.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  borrarCita,
  citasDelDia,
  citasDelMes,
  crearCita,
  listarClientes,
  marcarCitaHecha,
  TokenInvalido,
  type Cita,
  type ClienteListado,
} from '../api'
import { DIAS, MESES, hhmm, iso } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

export function Agenda({ token, onTokenInvalido }: Props) {
  const hoy = new Date()
  const hoyISO = iso(hoy)
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [diaElegido, setDiaElegido] = useState(hoyISO)
  const [delMes, setDelMes] = useState<Cita[]>([])
  const [delDia, setDelDia] = useState<Cita[]>([])
  const [clientes, setClientes] = useState<ClienteListado[]>([])
  const [recargas, setRecargas] = useState(0)
  const [error, setError] = useState('')
  const [abierto, setAbierto] = useState(false)

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

  // Rejilla del mes empezando en lunes: getDay() da 0 para domingo.
  const huecoInicial = (new Date(anio, mes - 1, 1).getDay() + 6) % 7
  const diasDelMes = new Date(anio, mes, 0).getDate()
  const celdas: (number | null)[] = [
    ...Array<null>(huecoInicial).fill(null),
    ...Array.from({ length: diasDelMes }, (_, i) => i + 1),
  ]
  const conCita = new Set(delMes.map((c) => c.fecha))

  function cambiarMes(salto: number) {
    const d = new Date(anio, mes - 1 + salto, 1)
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

  async function guardar(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const formulario = e.currentTarget
    const datos = new FormData(formulario)
    const titulo = String(datos.get('titulo') ?? '').trim()
    if (!titulo) return
    const cliente = String(datos.get('cliente') ?? '')
    await accion(async () => {
      await crearCita(token, {
        fecha: diaElegido,
        titulo,
        hora: String(datos.get('hora') ?? '') || null,
        direccion: String(datos.get('direccion') ?? '').trim() || null,
        cliente_id: cliente ? Number(cliente) : null,
      })
      formulario.reset()
      setAbierto(false)
    })
  }

  return (
    <>
      <section className="calendario">
        <header className="cal-cabecera">
          <button className="cal-flecha" onClick={() => cambiarMes(-1)} aria-label="Mes anterior">
            ‹
          </button>
          <h2>
            {MESES[mes - 1]} {anio}
          </h2>
          <button className="cal-flecha" onClick={() => cambiarMes(1)} aria-label="Mes siguiente">
            ›
          </button>
        </header>

        <div className="cal-rejilla">
          {DIAS.map((d) => (
            <span key={d} className="cal-dia-nombre">
              {d}
            </span>
          ))}
          {celdas.map((dia, i) => {
            if (dia === null) return <span key={`hueco-${i}`} />
            const fecha = iso(new Date(anio, mes - 1, dia))
            const clases = ['cal-dia']
            if (fecha === diaElegido) clases.push('elegido')
            if (fecha === hoyISO) clases.push('hoy')
            return (
              <button
                key={fecha}
                className={clases.join(' ')}
                onClick={() => setDiaElegido(fecha)}
              >
                {dia}
                {conCita.has(fecha) && <i className="punto" />}
              </button>
            )
          })}
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <section className="apuntes">
        <div className="titulo-fila">
          <h2>{diaElegido === hoyISO ? 'Hoy' : diaElegido.split('-').reverse().join('/')}</h2>
          <button className="enlace" onClick={() => setAbierto((v) => !v)}>
            {abierto ? 'Cancelar' : '+ Cita'}
          </button>
        </div>

        {abierto && (
          <form className="ficha-form" onSubmit={guardar}>
            <input name="titulo" placeholder="Qué hay que hacer" autoFocus aria-label="Título" />
            <div className="fila">
              <input name="hora" type="time" aria-label="Hora" />
              <select name="cliente" aria-label="Cliente" defaultValue="">
                <option value="">Sin cliente</option>
                {clientes.map((c) => (
                  <option key={c.cliente.id} value={c.cliente.id}>
                    {c.cliente.nombre}
                  </option>
                ))}
              </select>
            </div>
            <input name="direccion" placeholder="Dirección (opcional)" aria-label="Dirección" />
            <button type="submit">Guardar cita</button>
          </form>
        )}

        {delDia.length === 0 ? (
          <p className="vacio">Nada apuntado este día.</p>
        ) : (
          <ul>
            {delDia.map((c) => (
              <li key={c.id} className={c.hecha ? 'cita hecha' : 'cita'}>
                <span className="hora">{hhmm(c.hora) ?? '—'}</span>
                <span className="concepto">
                  {c.titulo}
                  {(c.cliente || c.direccion) && (
                    <small>
                      {c.cliente?.nombre}
                      {c.cliente && c.direccion ? ' · ' : ''}
                      {c.direccion}
                    </small>
                  )}
                </span>
                <button
                  className="mini"
                  onClick={() => void accion(() => marcarCitaHecha(token, c.id, !c.hecha))}
                  title={c.hecha ? 'Marcar como pendiente' : 'Marcar como hecha'}
                >
                  {c.hecha ? '↩' : '✓'}
                </button>
                <button
                  className="mini borrar"
                  onClick={() => void accion(() => borrarCita(token, c.id))}
                  title="Borrar"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
