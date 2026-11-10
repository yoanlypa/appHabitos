/** Pantalla de entrada: sin contraseñas, solo el token que da /web en el bot. */
import { useState } from 'react'
import { ErrorEnLinea } from '../ui/piezas'
import { Logo } from './Logo'

type Props = {
  onEntrar: (token: string) => void
  error?: string
}

export function Entrada({ onEntrar, error }: Props) {
  const [token, setToken] = useState('')

  return (
    <main className="entrada">
      <div className="tarjeta entrada-caja">
        <Logo lado={44} />
        <div>
          <h1>Parte del día</h1>
          <p className="ayuda">Tus trabajos, gastos, citas y hábitos en un solo sitio.</p>
        </div>

        <ol className="entrada-pasos">
          <li>
            <span>
              Escríbele <code>/web</code> al bot de Telegram.
            </span>
          </li>
          <li>
            <span>Toca «Abrir la web», o pega aquí el token que te dé.</span>
          </li>
        </ol>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (token.trim()) onEntrar(token.trim())
          }}
        >
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Tu token"
            autoFocus
            aria-label="Token de acceso"
          />
          <button type="submit" className="boton ancho" disabled={!token.trim()}>
            Entrar
          </button>
        </form>

        <ErrorEnLinea>{error}</ErrorEnLinea>
      </div>
    </main>
  )
}
