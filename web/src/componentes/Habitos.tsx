/**
 * Hábitos: lo que se quiere hacer con regularidad, y cómo va.
 *
 * La lista toma la idea de los buenos trackers: el nombre grande, la racha al
 * lado y los siete círculos de la semana, que se marcan con un toque. Nada de
 * formularios para lo diario: marcar tiene que costar lo mismo que mirar.
 *
 * El estado de cada círculo (hecho, hoy, fallado...) lo calcula el backend,
 * igual para la semana que para el calendario del detalle. Si también se
 * calculara aquí, habría dos sitios que deciden si una racha sigue viva, y el
 * día que no coincidieran nadie sabría cuál creerse.
 *
 * El detalle enseña racha, mejor racha y cumplimiento sobre el calendario del
 * mes, que es el mismo de la Agenda. Ahí también se marca, para corregir un
 * día pasado que se olvidó.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  borrarHabito,
  crearHabito,
  detalleHabito,
  editarHabito,
  listarHabitos,
  marcarDiaHabito,
  TokenInvalido,
  type DatosHabito,
  type DetalleHabito,
  type DiaHabito,
  type EstadoDia,
  type Habito,
  type ResumenHabito,
} from '../api'
import { DIAS, MESES } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

const TODOS = [0, 1, 2, 3, 4, 5, 6]
const LABORABLES = [0, 1, 2, 3, 4]

const DESCRIPCION: Record<EstadoDia, string> = {
  hecho: 'hecho',
  hoy: 'hoy, sin marcar',
  fallado: 'no se hizo',
  futuro: 'todavía no ha llegado',
  no_toca: 'no toca',
  antes: 'antes de empezar',
}

/** Lo que ya pasó o es hoy y tocaba; lo futuro y lo que no toca, no. */
function marcable(dia: DiaHabito) {
  return dia.estado !== 'futuro' && dia.estado !== 'no_toca'
}

function dias(n: number) {
  return `${n} ${n === 1 ? 'día' : 'días'}`
}

function racha(n: number) {
  return n === 1 ? '1 día seguido' : `${n} días seguidos`
}

function animo(n: number) {
  if (n >= 21) return 'Imparable 🔥'
  if (n >= 7) return 'Vas lanzado 🔥'
  if (n >= 1) return 'Sigue así'
  return 'Hoy es buen día para empezar'
}

export function Habitos({ token, onTokenInvalido }: Props) {
  const [habitos, setHabitos] = useState<ResumenHabito[]>([])
  const [abierto, setAbierto] = useState<number | null>(null)
  const [formulario, setFormulario] = useState<Habito | 'nuevo' | null>(null)
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
        const lista = await listarHabitos(token)
        if (cancelado) return
        setHabitos(lista)
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
  }, [token, recargas, fallo])

  async function accion(hacer: () => Promise<unknown>) {
    try {
      setError('')
      await hacer()
      setRecargas((n) => n + 1)
    } catch (e) {
      fallo(e)
    }
  }

  function tocar(habito: Habito, dia: DiaHabito) {
    if (!marcable(dia)) return
    void accion(() => marcarDiaHabito(token, habito.id, dia.fecha, dia.estado !== 'hecho'))
  }

  const editando = formulario !== null && formulario !== 'nuevo' ? formulario : null

  const ventana = formulario !== null && (
    <FormularioHabito
      inicial={editando}
      onCerrar={() => setFormulario(null)}
      onGuardar={(datos) =>
        accion(async () => {
          if (editando) await editarHabito(token, editando.id, datos)
          else await crearHabito(token, datos)
          setFormulario(null)
        })
      }
      onBorrar={
        editando
          ? () =>
              accion(async () => {
                await borrarHabito(token, editando.id)
                setFormulario(null)
                setAbierto(null)
              })
          : undefined
      }
    />
  )

  if (abierto !== null) {
    return (
      <>
        {error && <p className="error">{error}</p>}
        <DetalleDeHabito
          token={token}
          habitoId={abierto}
          recargas={recargas}
          onVolver={() => setAbierto(null)}
          onEditar={setFormulario}
          onMarcar={tocar}
          onFallo={fallo}
        />
        {ventana}
      </>
    )
  }

  return (
    <section className="habitos">
      <div className="habitos-cabecera">
        <h2>Hábitos</h2>
        <button
          className="boton-redondo"
          onClick={() => setFormulario('nuevo')}
          aria-label="Nuevo hábito"
        >
          +
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {cargando ? (
        <p className="vacio">Cargando…</p>
      ) : habitos.length === 0 ? (
        <div className="habitos-vacio">
          <p className="vacio">Todavía no tienes hábitos.</p>
          <button onClick={() => setFormulario('nuevo')}>Crear el primero</button>
        </div>
      ) : (
        <ul className="lista-habitos">
          {habitos.map((r) => (
            <li key={r.habito.id} className="habito">
              <button className="habito-titulo" onClick={() => setAbierto(r.habito.id)}>
                <span className="nombre">{r.habito.nombre}</span>
                {r.racha > 0 && <span className="racha">{racha(r.racha)}</span>}
              </button>
              <div className="semana-habito">
                {r.semana.map((d, i) => (
                  <button
                    key={d.fecha}
                    className={`circulo ${d.estado}`}
                    disabled={!marcable(d)}
                    aria-pressed={d.estado === 'hecho'}
                    aria-label={`${DIAS[i]}: ${DESCRIPCION[d.estado]}`}
                    onClick={() => tocar(r.habito, d)}
                  >
                    {DIAS[i]}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      {ventana}
    </section>
  )
}

function DetalleDeHabito({
  token,
  habitoId,
  recargas,
  onVolver,
  onEditar,
  onMarcar,
  onFallo,
}: {
  token: string
  habitoId: number
  recargas: number
  onVolver: () => void
  onEditar: (habito: Habito) => void
  onMarcar: (habito: Habito, dia: DiaHabito) => void
  onFallo: (e: unknown) => void
}) {
  const hoy = new Date()
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [detalle, setDetalle] = useState<DetalleHabito | null>(null)

  useEffect(() => {
    let cancelado = false
    detalleHabito(token, habitoId, anio, mes)
      .then((d) => {
        if (!cancelado) setDetalle(d)
      })
      .catch((e) => {
        if (!cancelado) onFallo(e)
      })
    return () => {
      cancelado = true
    }
  }, [token, habitoId, anio, mes, recargas, onFallo])

  function cambiarMes(salto: number) {
    const d = new Date(anio, mes - 1 + salto, 1)
    setAnio(d.getFullYear())
    setMes(d.getMonth() + 1)
  }

  if (!detalle) return <p className="vacio">Cargando…</p>

  const { habito } = detalle
  // Rejilla empezando en lunes: getDay() da 0 para domingo.
  const hueco = (new Date(anio, mes - 1, 1).getDay() + 6) % 7
  const esRecord = detalle.mejor_racha > 0 && detalle.racha === detalle.mejor_racha

  return (
    <section className="habito-detalle">
      <header className="detalle-cabecera">
        <button className="boton-redondo" onClick={onVolver} aria-label="Volver">
          ‹
        </button>
        <h2>{habito.nombre}</h2>
        <button className="boton-redondo" onClick={() => onEditar(habito)} aria-label="Editar">
          ⋯
        </button>
      </header>

      <dl className="cifras">
        <div>
          <dt>Racha actual</dt>
          <dd>{dias(detalle.racha)}</dd>
          <small>{animo(detalle.racha)}</small>
        </div>
        <div>
          <dt>Mejor racha</dt>
          <dd>{dias(detalle.mejor_racha)}</dd>
          {esRecord && <small>Es tu récord</small>}
        </div>
        <div>
          <dt>Cumplimiento</dt>
          <dd>{detalle.porcentaje}%</dd>
          <small>
            {detalle.cumplidos} de {dias(detalle.programados)}
          </small>
        </div>
      </dl>

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
          {Array.from({ length: hueco }, (_, i) => (
            <span key={`hueco-${i}`} />
          ))}
          {detalle.dias_del_mes.map((d) => (
            <button
              key={d.fecha}
              className={`cal-dia ${d.estado}`}
              disabled={!marcable(d)}
              aria-pressed={d.estado === 'hecho'}
              aria-label={`${Number(d.fecha.slice(8))}: ${DESCRIPCION[d.estado]}`}
              onClick={() => onMarcar(habito, d)}
            >
              {Number(d.fecha.slice(8))}
            </button>
          ))}
        </div>
      </section>

      <p className="ayuda">
        Toca: {habito.dias.map((d) => DIAS[d]).join(' ')}.{' '}
        {habito.recordar_a
          ? `Te lo recuerdo por Telegram a las ${habito.recordar_a.slice(0, 5)}.`
          : 'Sin recordatorio: puedes ponerle uno en ⋯.'}
      </p>
    </section>
  )
}

function FormularioHabito({
  inicial,
  onCerrar,
  onGuardar,
  onBorrar,
}: {
  inicial: Habito | null
  onCerrar: () => void
  onGuardar: (datos: DatosHabito) => Promise<void>
  onBorrar?: () => Promise<void>
}) {
  const [nombre, setNombre] = useState(inicial?.nombre ?? '')
  const [elegidos, setElegidos] = useState<number[]>(inicial?.dias ?? TODOS)
  const [conRecordatorio, setConRecordatorio] = useState(Boolean(inicial?.recordar_a))
  const [hora, setHora] = useState(inicial?.recordar_a?.slice(0, 5) ?? '09:00')

  const valido = nombre.trim() !== '' && elegidos.length > 0

  function alternarDia(dia: number) {
    setElegidos((actual) =>
      actual.includes(dia) ? actual.filter((d) => d !== dia) : [...actual, dia].sort(),
    )
  }

  function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (!valido) return
    void onGuardar({
      nombre: nombre.trim(),
      dias: elegidos,
      recordar_a: conRecordatorio && hora ? hora : null,
    })
  }

  return (
    <div
      className="modal-fondo"
      role="dialog"
      aria-modal="true"
      aria-label={inicial ? 'Editar hábito' : 'Nuevo hábito'}
    >
      <form className="modal" onSubmit={enviar}>
        <h3>{inicial ? 'Editar hábito' : 'Nuevo hábito'}</h3>

        <label>
          Qué quieres hacer
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Beber agua"
            autoFocus
          />
        </label>

        <fieldset className="dias-habito">
          <legend>Qué días</legend>
          <div className="semana-habito">
            {DIAS.map((letra, i) => (
              <button
                key={letra}
                type="button"
                className={`circulo ${elegidos.includes(i) ? 'hecho' : 'futuro'}`}
                aria-pressed={elegidos.includes(i)}
                onClick={() => alternarDia(i)}
              >
                {letra}
              </button>
            ))}
          </div>
          <div className="atajos">
            <button type="button" className="enlace" onClick={() => setElegidos(TODOS)}>
              Todos
            </button>
            <button type="button" className="enlace" onClick={() => setElegidos(LABORABLES)}>
              De lunes a viernes
            </button>
          </div>
        </fieldset>

        <label className="casilla">
          <input
            type="checkbox"
            checked={conRecordatorio}
            onChange={(e) => setConRecordatorio(e.target.checked)}
          />
          Recordármelo por Telegram
        </label>
        {conRecordatorio && (
          <label>
            A las
            <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
          </label>
        )}

        {elegidos.length === 0 && <p className="error">Elige al menos un día.</p>}

        {onBorrar && (
          <button
            type="button"
            className="enlace peligro"
            onClick={() => {
              if (confirm(`¿Borrar «${inicial?.nombre}» con todo su historial?`)) void onBorrar()
            }}
          >
            Borrar este hábito
          </button>
        )}

        <div className="botones">
          <button type="button" className="enlace" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" disabled={!valido}>
            {inicial ? 'Guardar' : 'Crear hábito'}
          </button>
        </div>
      </form>
    </div>
  )
}
