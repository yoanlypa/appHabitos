/**
 * Hábitos: lo que se quiere hacer con regularidad, y cómo va.
 *
 * La lista toma la idea de los buenos trackers: el nombre, la racha al lado y
 * los siete círculos de la semana, que se marcan con un toque. Nada de
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
import { ArrowLeft, Bell, Check, Flame, Pencil, Plus, Trash2 } from 'lucide-react'
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
import { confirmar } from '../ui/avisos'
import { Calendario } from '../ui/Calendario'
import { Modal } from '../ui/Modal'
import { Cabecera, ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { DIAS } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

const TODOS = [0, 1, 2, 3, 4, 5, 6]
const LABORABLES = [0, 1, 2, 3, 4]
const NOMBRES_DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

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

function animo(n: number) {
  if (n >= 21) return 'Imparable'
  if (n >= 7) return 'Vas lanzado'
  if (n >= 1) return 'Sigue así'
  return 'Hoy es buen día para empezar'
}

/** "Todos los días", "De lunes a viernes" o "L · X · V". */
function cuando(elegidos: number[]) {
  if (elegidos.length === 7) return 'Todos los días'
  if (elegidos.join('') === '01234') return 'De lunes a viernes'
  if (elegidos.join('') === '56') return 'Fines de semana'
  return elegidos.map((d) => DIAS[d]).join(' · ')
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
        <ErrorEnLinea>{error}</ErrorEnLinea>
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

  const deHoy = habitos.filter((h) => h.toca_hoy)
  const hechosHoy = deHoy.filter((h) => h.hecho_hoy).length

  return (
    <>
      <Cabecera
        titulo="Hábitos"
        subtitulo={
          deHoy.length > 0
            ? hechosHoy === deHoy.length
              ? 'Hoy lo llevas todo hecho.'
              : `Hoy llevas ${hechosHoy} de ${deHoy.length}.`
            : undefined
        }
      >
        <button className="boton" onClick={() => setFormulario('nuevo')}>
          <Plus size={18} />
          Nuevo hábito
        </button>
      </Cabecera>

      {deHoy.length > 0 && (
        <div
          className="progreso grande"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={deHoy.length}
          aria-valuenow={hechosHoy}
        >
          <i style={{ width: `${(hechosHoy / deHoy.length) * 100}%` }} />
        </div>
      )}

      <ErrorEnLinea>{error}</ErrorEnLinea>

      {cargando ? (
        <Esqueleto />
      ) : habitos.length === 0 ? (
        <div className="tarjeta">
          <Vacio icono={Flame} titulo="Todavía no tienes hábitos">
            Beber agua, estirar, repasar las cuentas el viernes…
            <button className="boton" onClick={() => setFormulario('nuevo')}>
              Crear el primero
            </button>
          </Vacio>
        </div>
      ) : (
        <ul className="lista-habitos">
          {habitos.map((r) => (
            <li key={r.habito.id} className="tarjeta habito">
              <button className="habito-titulo" onClick={() => setAbierto(r.habito.id)}>
                <span>
                  <strong>{r.habito.nombre}</strong>
                  <small>
                    {cuando(r.habito.dias)}
                    {r.habito.recordar_a && (
                      <>
                        {' · '}
                        <Bell size={11} /> {r.habito.recordar_a.slice(0, 5)}
                      </>
                    )}
                  </small>
                </span>
                <span className={r.racha > 0 ? 'racha viva' : 'racha'} title="Días seguidos">
                  <Flame size={15} />
                  {r.racha}
                </span>
              </button>
              <div className="semana-habito">
                {r.semana.map((d, i) => (
                  <button
                    key={d.fecha}
                    className={`circulo ${d.estado}`}
                    disabled={!marcable(d)}
                    aria-pressed={d.estado === 'hecho'}
                    aria-label={`${NOMBRES_DIAS[i]}: ${DESCRIPCION[d.estado]}`}
                    onClick={() => tocar(r.habito, d)}
                  >
                    <span>{DIAS[i]}</span>
                    <i>{d.estado === 'hecho' && <Check size={16} strokeWidth={3} />}</i>
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}

      {ventana}
    </>
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

  if (!detalle) return <Esqueleto />

  const { habito } = detalle
  const esRecord = detalle.mejor_racha > 0 && detalle.racha === detalle.mejor_racha
  const porFecha = new Map(detalle.dias_del_mes.map((d) => [d.fecha, d]))

  return (
    <>
      <button className="enlace gris volver" onClick={onVolver}>
        <ArrowLeft size={16} />
        Todos los hábitos
      </button>

      <Cabecera
        titulo={habito.nombre}
        subtitulo={
          <>
            {cuando(habito.dias)}
            {' · '}
            {habito.recordar_a
              ? `recordatorio por Telegram a las ${habito.recordar_a.slice(0, 5)}`
              : 'sin recordatorio'}
          </>
        }
      >
        <button className="boton secundario" onClick={() => onEditar(habito)}>
          <Pencil size={16} />
          Editar
        </button>
      </Cabecera>

      <dl className="kpis tres">
        <Kpi nombre="Racha actual" valor={dias(detalle.racha)} nota={animo(detalle.racha)} />
        <Kpi
          nombre="Mejor racha"
          valor={dias(detalle.mejor_racha)}
          nota={esRecord ? 'Es tu récord' : undefined}
        />
        <Kpi
          nombre="Cumplimiento"
          valor={`${detalle.porcentaje}%`}
          nota={`${detalle.cumplidos} de ${dias(detalle.programados)}`}
        />
      </dl>

      <div className="tarjeta habito-calendario">
        <Calendario
          anio={anio}
          mes={mes}
          onMes={(a, m) => {
            setAnio(a)
            setMes(m)
          }}
          onDia={(fecha) => {
            const dia = porFecha.get(fecha)
            if (dia) onMarcar(habito, dia)
          }}
          celda={(fecha) => {
            const dia = porFecha.get(fecha)
            if (!dia) return { desactivado: true }
            return {
              clase: dia.estado,
              desactivado: !marcable(dia),
              pulsado: dia.estado === 'hecho',
              etiqueta: `${Number(fecha.slice(8))}: ${DESCRIPCION[dia.estado]}`,
            }
          }}
        />
        <p className="ayuda">Toca un día pasado para marcarlo o desmarcarlo.</p>
      </div>
    </>
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

  async function borrar() {
    if (!onBorrar || !inicial) return
    const si = await confirmar({
      titulo: `¿Borrar «${inicial.nombre}»?`,
      texto: 'Se borra con todo su historial y su racha. No se puede deshacer.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (si) void onBorrar()
  }

  return (
    <Modal titulo={inicial ? 'Editar hábito' : 'Nuevo hábito'} onCerrar={onCerrar}>
      <form className="formulario" onSubmit={enviar}>
        <label className="campo">
          Qué quieres hacer
          <input
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            placeholder="Beber agua"
            autoFocus={!inicial}
          />
        </label>

        <fieldset className="dias-habito">
          <legend>Qué días</legend>
          <div className="semana-habito">
            {DIAS.map((letra, i) => (
              <button
                key={letra}
                type="button"
                className={`circulo ${elegidos.includes(i) ? 'hecho' : 'libre'}`}
                aria-pressed={elegidos.includes(i)}
                aria-label={NOMBRES_DIAS[i]}
                onClick={() => alternarDia(i)}
              >
                <i>{letra}</i>
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
          <label className="campo">
            A las
            <input type="time" value={hora} onChange={(e) => setHora(e.target.value)} />
          </label>
        )}

        {elegidos.length === 0 && <ErrorEnLinea>Elige al menos un día.</ErrorEnLinea>}

        <div className="botones">
          {onBorrar && (
            <button
              type="button"
              className="boton-icono peligro"
              onClick={() => void borrar()}
              aria-label="Borrar este hábito"
              title="Borrar este hábito"
            >
              <Trash2 size={18} />
            </button>
          )}
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!valido}>
              {inicial ? 'Guardar' : 'Crear hábito'}
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}
