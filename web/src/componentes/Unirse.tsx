/**
 * La pantalla a la que lleva el enlace de invitación a Casa.
 *
 * Quien llega no tiene token ni Telegram por fuerza: con su nombre basta. El
 * backend le da un token, que se guarda como el de siempre, y a partir de ahí
 * la web solo le enseña Casa.
 *
 * Quien ya estaba (entró solo por la web y cerró sesión o cambió de móvil)
 * elige su nombre y sigue siendo la misma persona, con lo que anotó, en vez
 * de salir dos veces en Personas.
 */
import { useEffect, useState } from 'react'
import { unirseACasa, verInvitacion, type InvitacionVista } from '../api'
import { ErrorEnLinea } from '../ui/piezas'
import { Logo } from './Logo'

type Props = {
  codigo: string
  onDentro: (token: string) => void
  onCancelar: () => void
}

export function Unirse({ codigo, onDentro, onCancelar }: Props) {
  const [casa, setCasa] = useState<InvitacionVista | null>(null)
  const [nombre, setNombre] = useState('')
  const [error, setError] = useState('')
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    verInvitacion(codigo).then(setCasa, (e: Error) => setError(e.message))
  }, [codigo])

  async function entrarComo(miembroId?: number) {
    setOcupado(true)
    setError('')
    try {
      onDentro(await unirseACasa(codigo, nombre.trim(), miembroId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No se ha podido entrar')
      setOcupado(false)
    }
  }

  async function entrar(e: React.FormEvent) {
    e.preventDefault()
    if (!nombre.trim()) return
    await entrarComo()
  }

  return (
    <main className="entrada">
      <div className="tarjeta entrada-caja">
        <Logo lado={44} />
        <div>
          <h1>Te invitan a Casa</h1>
          <p className="ayuda">
            {casa
              ? `Con ${casa.miembros.join(' y ')}. Para apuntar juntos los gastos de casa y la lista de la compra.`
              : 'Para apuntar juntos los gastos de casa y la lista de la compra.'}
          </p>
        </div>

        {casa && casa.volver.length > 0 && (
          <div className="volver-a-casa">
            <p className="ayuda">¿Ya estabas en esta casa? Toca tu nombre:</p>
            {casa.volver.map((p) => (
              <button
                key={p.id}
                type="button"
                className="boton secundario ancho"
                onClick={() => void entrarComo(p.id)}
                disabled={ocupado}
              >
                Soy {p.nombre}
              </button>
            ))}
            <p className="ayuda">Si eres alguien nuevo, escribe tu nombre:</p>
          </div>
        )}

        {casa && (
          <form onSubmit={entrar}>
            <input
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Tu nombre"
              aria-label="Tu nombre"
              maxLength={40}
              autoFocus
            />
            <button type="submit" className="boton ancho" disabled={!nombre.trim() || ocupado}>
              {ocupado ? 'Entrando…' : 'Entrar'}
            </button>
          </form>
        )}

        <ErrorEnLinea>{error}</ErrorEnLinea>
        {error && (
          <button className="enlace gris" onClick={onCancelar}>
            Ir a la entrada normal
          </button>
        )}
      </div>
    </main>
  )
}
