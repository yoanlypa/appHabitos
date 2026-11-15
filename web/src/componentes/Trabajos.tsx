/**
 * Trabajos: las obras, como una base de datos de Notion.
 *
 * La lista enseña cada trabajo con sus propiedades a la vista (cliente,
 * fechas, facturado, reseña y lo que deja) y se filtra con un toque. En el
 * ordenador es una tabla; en el móvil, tarjetas, que una tabla de seis
 * columnas no cabe en una mano.
 *
 * Tocar uno abre su ficha (`FichaTrabajo.tsx`). La ficha va en la dirección
 * (`#/trabajos/12`), así el botón de atrás del móvil vuelve a la lista.
 *
 * Las cuentas de cada trabajo las da el backend; aquí solo se pintan.
 */
import {
  BadgeCheck,
  Calendar,
  ChevronRight,
  Hammer,
  Plus,
  Search,
  Star,
  StickyNote,
  User,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  crearTrabajo,
  listarClientes,
  listarTrabajos,
  TokenInvalido,
  type ClienteListado,
  type TrabajoListado,
} from '../api'
import { avisar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { Cabecera, ErrorEnLinea, Esqueleto, Vacio } from '../ui/piezas'
import { diaRelativo, euros, fechasDe, iso, terminado } from '../utiles'
import { FichaTrabajo } from './FichaTrabajo'

type Props = {
  token: string
  onTokenInvalido: () => void
}

const FILTROS = [
  { id: 'todos', nombre: 'Todos' },
  { id: 'en_curso', nombre: 'En curso' },
  { id: 'terminados', nombre: 'Terminados' },
  { id: 'sin_facturar', nombre: 'Sin facturar' },
  { id: 'sin_resena', nombre: 'Sin reseña' },
] as const
type Filtro = (typeof FILTROS)[number]['id']

function pasa(t: TrabajoListado, filtro: Filtro) {
  const acabado = terminado(t.trabajo.fecha_fin)
  switch (filtro) {
    case 'en_curso':
      return !acabado
    case 'terminados':
      return acabado
    case 'sin_facturar':
      return !t.trabajo.facturado
    case 'sin_resena':
      // Solo tiene sentido pedirla de lo acabado.
      return acabado && !t.trabajo.resena
    default:
      return true
  }
}

/** Cambia la dirección; fuera del componente, que React no quiere que se toque `window` desde dentro. */
function irA(ruta: string) {
  window.location.hash = ruta
}

/** El id del trabajo abierto, si la dirección es "#/trabajos/12". */
function abiertoEnLaDireccion(): number | null {
  const partes = window.location.hash.replace(/^#\/?/, '').split('/')
  const id = Number(partes[1])
  return partes[0] === 'trabajos' && Number.isInteger(id) && id > 0 ? id : null
}

export function Trabajos({ token, onTokenInvalido }: Props) {
  const [abierto, setAbierto] = useState<number | null>(abiertoEnLaDireccion)
  const [lista, setLista] = useState<TrabajoListado[]>([])
  const [filtro, setFiltro] = useState<Filtro>('todos')
  const [buscar, setBuscar] = useState('')
  const [nuevo, setNuevo] = useState(false)
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

  useEffect(() => {
    const alCambiar = () => setAbierto(abiertoEnLaDireccion())
    window.addEventListener('hashchange', alCambiar)
    return () => window.removeEventListener('hashchange', alCambiar)
  }, [])

  useEffect(() => {
    if (abierto !== null) return
    let cancelado = false
    listarTrabajos(token)
      .then((l) => {
        if (cancelado) return
        setLista(l)
        setError('')
      })
      .catch((e) => {
        if (!cancelado) fallo(e)
      })
      .finally(() => !cancelado && setCargando(false))
    return () => {
      cancelado = true
    }
  }, [token, abierto, recargas, fallo])

  function abrir(id: number) {
    irA(`/trabajos/${id}`)
    window.scrollTo(0, 0)
  }

  function volver() {
    irA('/trabajos')
    setRecargas((n) => n + 1)
  }

  const cuantos = useMemo(
    () => Object.fromEntries(FILTROS.map((f) => [f.id, lista.filter((t) => pasa(t, f.id)).length])),
    [lista],
  )
  const texto = buscar.trim().toLowerCase()
  const visibles = lista.filter(
    (t) =>
      pasa(t, filtro) &&
      (!texto ||
        t.trabajo.titulo.toLowerCase().includes(texto) ||
        (t.trabajo.cliente?.nombre.toLowerCase().includes(texto) ?? false)),
  )

  if (abierto !== null) {
    return (
      <FichaTrabajo
        key={abierto}
        token={token}
        trabajoId={abierto}
        onTokenInvalido={onTokenInvalido}
        onVolver={volver}
      />
    )
  }

  return (
    <>
      <Cabecera titulo="Trabajos" subtitulo="Tus obras, con todo lo que llevan dentro.">
        <button className="boton" onClick={() => setNuevo(true)}>
          <Plus size={18} />
          Nuevo trabajo
        </button>
      </Cabecera>

      <ErrorEnLinea>{error}</ErrorEnLinea>

      <div className="barra-base">
        <label className="buscador">
          <Search size={17} />
          <input
            value={buscar}
            onChange={(e) => setBuscar(e.target.value)}
            placeholder="Buscar por trabajo o cliente"
            aria-label="Buscar trabajo"
          />
        </label>
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
      </div>

      {cargando ? (
        <div className="tarjeta">
          <Esqueleto />
        </div>
      ) : lista.length === 0 ? (
        <div className="tarjeta">
          <Vacio icono={Hammer} titulo="Todavía no tienes trabajos">
            Crea uno por obra y mete dentro sus cobros, gastos, notas y citas.
            <button className="boton" onClick={() => setNuevo(true)}>
              Crear el primero
            </button>
          </Vacio>
        </div>
      ) : visibles.length === 0 ? (
        <div className="tarjeta">
          <Vacio icono={Search} titulo="Ningún trabajo con ese filtro" />
        </div>
      ) : (
        <div className="tarjeta base-datos">
          <div className="base-cabecera" aria-hidden="true">
            <span>Trabajo</span>
            <span>
              <User size={14} /> Cliente
            </span>
            <span>
              <Calendar size={14} /> Fechas
            </span>
            <span>
              <BadgeCheck size={14} /> Facturado
            </span>
            <span>
              <Star size={14} /> Reseña
            </span>
            <span className="derecha">Queda</span>
          </div>
          <ul>
            {visibles.map((t) => (
              <FilaTrabajo key={t.trabajo.id} t={t} onAbrir={() => abrir(t.trabajo.id)} />
            ))}
          </ul>
        </div>
      )}

      {nuevo && (
        <NuevoTrabajo
          token={token}
          onCerrar={() => setNuevo(false)}
          onCreado={(id) => {
            setNuevo(false)
            avisar('Trabajo creado')
            abrir(id)
          }}
          onFallo={fallo}
        />
      )}
    </>
  )
}

function FilaTrabajo({ t, onAbrir }: { t: TrabajoListado; onAbrir: () => void }) {
  const { trabajo: tr, cuentas } = t
  const acabado = terminado(tr.fecha_fin)
  const queda = Number(cuentas.beneficio)
  return (
    <li
      className="base-fila"
      role="button"
      tabIndex={0}
      onClick={onAbrir}
      onKeyDown={(e) => e.key === 'Enter' && onAbrir()}
    >
      <span className="base-titulo">
        <span className={acabado ? 'estado-obra acabada' : 'estado-obra'} aria-hidden="true" />
        <strong>{tr.titulo}</strong>
        <small className="solo-movil">
          {tr.cliente?.nombre ?? 'Sin cliente'} · {fechasDe(tr.fecha_inicio, tr.fecha_fin)}
        </small>
        {(t.notas_pendientes > 0 || t.proxima_cita) && (
          <small className="base-extra">
            {t.proxima_cita && (
              <span>
                <Calendar size={12} /> {diaRelativo(t.proxima_cita.fecha)}
                {t.proxima_cita.hora ? ` ${t.proxima_cita.hora.slice(0, 5)}` : ''}
              </span>
            )}
            {t.notas_pendientes > 0 && (
              <span>
                <StickyNote size={12} /> {t.notas_pendientes}
              </span>
            )}
          </small>
        )}
      </span>
      <span className="base-celda solo-pc">{tr.cliente?.nombre ?? <i>Sin cliente</i>}</span>
      <span className="base-celda solo-pc">{fechasDe(tr.fecha_inicio, tr.fecha_fin)}</span>
      <span className="base-celda base-pastillas">
        <span className={tr.facturado ? 'pastilla acento' : 'pastilla'}>
          {tr.facturado ? 'Facturado' : 'Sin facturar'}
        </span>
        <span className={tr.resena ? 'pastilla pendiente' : 'pastilla solo-pc'}>
          {tr.resena ? '★ Reseña' : 'Sin reseña'}
        </span>
      </span>
      <span className="base-celda derecha">
        <b className={queda < 0 ? 'gasto' : ''}>{euros(cuentas.beneficio)}</b>
        {Number(cuentas.pendiente) > 0 && (
          <small className="pendiente">{euros(cuentas.pendiente)} por cobrar</small>
        )}
      </span>
      <ChevronRight size={18} className="base-flecha" />
    </li>
  )
}

function NuevoTrabajo({
  token,
  onCerrar,
  onCreado,
  onFallo,
}: {
  token: string
  onCerrar: () => void
  onCreado: (id: number) => void
  onFallo: (e: unknown) => void
}) {
  const [titulo, setTitulo] = useState('')
  const [cliente, setCliente] = useState('')
  const [inicio, setInicio] = useState(iso(new Date()))
  const [clientes, setClientes] = useState<ClienteListado[]>([])
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    listarClientes(token)
      .then(setClientes)
      .catch(() => {})
  }, [token])

  async function crear(e: React.FormEvent) {
    e.preventDefault()
    if (!titulo.trim()) return
    setOcupado(true)
    try {
      const t = await crearTrabajo(token, {
        titulo: titulo.trim(),
        cliente_id: cliente ? Number(cliente) : null,
        fecha_inicio: inicio || null,
      })
      onCreado(t.id)
    } catch (err) {
      onFallo(err)
      setOcupado(false)
    }
  }

  return (
    <Modal titulo="Nuevo trabajo" onCerrar={onCerrar}>
      <form className="formulario" onSubmit={crear}>
        <label className="campo">
          Nombre
          <input
            value={titulo}
            onChange={(e) => setTitulo(e.target.value)}
            placeholder="Reforma baño calle Mayor"
            autoFocus
          />
        </label>
        <div className="dos-campos">
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
            Empieza
            <input type="date" value={inicio} onChange={(e) => setInicio(e.target.value)} />
          </label>
        </div>
        <p className="ayuda">El resto (fin, facturado, reseña) se pone dentro, cuando toque.</p>
        <div className="botones">
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!titulo.trim() || ocupado}>
              Crear y abrir
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}
