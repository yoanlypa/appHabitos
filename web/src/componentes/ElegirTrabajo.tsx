/**
 * Elegir de qué trabajo es uno o varios movimientos, sin abrirlos.
 *
 * Sale al tocar el botoncito del trabajo de una fila, con el clic derecho
 * sobre ella, o con varios seleccionados. Lista los trabajos con buscador; si
 * lo escrito no existe, se puede crear ahí mismo y quedan dentro. Se guarda
 * todo de una vez (`POST /apuntes/trabajo`): o todos o ninguno.
 */
import { Check, Hammer, Plus, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { asignarTrabajo, crearTrabajo, listarTrabajos, type Apunte, type Trabajo } from '../api'
import { avisar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea, Esqueleto } from '../ui/piezas'

type Props = {
  token: string
  apuntes: Apunte[]
  onHecho: () => void
  onCerrar: () => void
}

export function ElegirTrabajo({ token, apuntes, onHecho, onCerrar }: Props) {
  const [trabajos, setTrabajos] = useState<Trabajo[] | null>(null)
  const [buscar, setBuscar] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    listarTrabajos(token)
      .then((l) => setTrabajos(l.map((t) => t.trabajo)))
      .catch((e) => setError(e instanceof Error ? e.message : 'No se han podido leer los trabajos'))
  }, [token])

  // Si todos están ya en el mismo trabajo, ese sale marcado.
  const actual = apuntes.every((a) => a.trabajo_id === apuntes[0]?.trabajo_id)
    ? (apuntes[0]?.trabajo_id ?? null)
    : undefined
  const texto = buscar.trim().toLowerCase()
  const visibles = (trabajos ?? []).filter(
    (t) =>
      !texto ||
      t.titulo.toLowerCase().includes(texto) ||
      (t.cliente?.nombre.toLowerCase().includes(texto) ?? false),
  )
  const existe = (trabajos ?? []).some((t) => t.titulo.toLowerCase() === texto)

  async function elegir(id: number | null, titulo?: string) {
    setOcupado(true)
    setError('')
    try {
      await asignarTrabajo(
        token,
        apuntes.map((a) => a.id),
        id,
      )
      const cuantos = apuntes.length === 1 ? apuntes[0].concepto : `${apuntes.length} movimientos`
      avisar(id === null ? `${cuantos} · sin trabajo` : `${cuantos} → ${titulo}`)
      onHecho()
      onCerrar()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se ha podido guardar')
      setOcupado(false)
    }
  }

  async function crearYElegir() {
    setOcupado(true)
    try {
      const nuevo = await crearTrabajo(token, { titulo: buscar.trim() })
      await elegir(nuevo.id, nuevo.titulo)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se ha podido crear el trabajo')
      setOcupado(false)
    }
  }

  return (
    <Modal
      titulo={apuntes.length === 1 ? '¿De qué trabajo es?' : `¿De qué trabajo son estos ${apuntes.length}?`}
      onCerrar={onCerrar}
      estrecha
    >
      <div className="elegir-trabajo">
        {apuntes.length === 1 && <p className="ayuda">{apuntes[0].concepto}</p>}
        <label className="buscador">
          <Search size={17} />
          <input
            value={buscar}
            onChange={(e) => setBuscar(e.target.value)}
            placeholder="Buscar o crear un trabajo"
            aria-label="Buscar trabajo"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && visibles.length === 1) void elegir(visibles[0].id, visibles[0].titulo)
            }}
          />
        </label>
        <ErrorEnLinea>{error}</ErrorEnLinea>
        {trabajos === null ? (
          <Esqueleto />
        ) : (
          <ul className="opciones-trabajo">
            {visibles.map((t) => (
              <li key={t.id}>
                <button disabled={ocupado} onClick={() => void elegir(t.id, t.titulo)}>
                  <Hammer size={16} />
                  <span>
                    {t.titulo}
                    {t.cliente && <small>{t.cliente.nombre}</small>}
                  </span>
                  {actual === t.id && <Check size={16} className="elegido" />}
                </button>
              </li>
            ))}
            {texto && !existe && (
              <li>
                <button disabled={ocupado} className="crear" onClick={() => void crearYElegir()}>
                  <Plus size={16} />
                  <span>Crear el trabajo «{buscar.trim()}»</span>
                </button>
              </li>
            )}
            {!texto && visibles.length === 0 && (
              <li className="ayuda">Todavía no tienes trabajos: escribe un nombre para crear uno.</li>
            )}
            {actual !== null && (
              <li>
                <button disabled={ocupado} className="quitar" onClick={() => void elegir(null)}>
                  <X size={16} />
                  <span>Sin trabajo</span>
                </button>
              </li>
            )}
          </ul>
        )}
      </div>
    </Modal>
  )
}
