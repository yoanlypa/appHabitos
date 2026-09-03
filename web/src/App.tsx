/**
 * Decide qué pantalla toca: entrada si no hay token, panel si lo hay.
 *
 * El token se guarda en localStorage porque esto se abre desde el móvil y
 * nadie quiere pegar un token cada vez. Si el backend lo rechaza, se borra
 * y se vuelve a la pantalla de entrada.
 */
import { useState } from 'react'
import { Entrada } from './componentes/Entrada'
import { Panel } from './componentes/Panel'
import './App.css'

const CLAVE = 'parte-del-dia:token'

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(CLAVE) ?? '')
  const [error, setError] = useState('')

  function entrar(nuevo: string) {
    localStorage.setItem(CLAVE, nuevo)
    setError('')
    setToken(nuevo)
  }

  function salir(motivo = '') {
    localStorage.removeItem(CLAVE)
    setError(motivo)
    setToken('')
  }

  if (!token) return <Entrada onEntrar={entrar} error={error} />

  return (
    <Panel
      token={token}
      onSalir={() => salir()}
      onTokenInvalido={() => salir('Ese token ya no vale. Pide otro con /web en el bot.')}
    />
  )
}
