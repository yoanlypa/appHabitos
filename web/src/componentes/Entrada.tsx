/** Pantalla de entrada: sin contraseñas, solo el token que da /web en el bot. */
import { useState } from 'react'

type Props = {
  onEntrar: (token: string) => void
  error?: string
}

export function Entrada({ onEntrar, error }: Props) {
  const [token, setToken] = useState('')

  return (
    <main className="entrada">
      <h1>Parte del día</h1>
      <p className="ayuda">
        Escríbele <code>/web</code> al bot de Telegram y pega aquí el token que te dé.
      </p>

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
        <button type="submit" disabled={!token.trim()}>
          Entrar
        </button>
      </form>

      {error && <p className="error">{error}</p>}
    </main>
  )
}
