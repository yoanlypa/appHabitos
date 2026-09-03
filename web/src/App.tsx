/**
 * Decide qué pantalla toca y mantiene la navegación entre secciones.
 *
 * La barra va abajo a propósito: esto se usa con una mano, de pie, en casa
 * de un cliente, y abajo es donde llega el pulgar.
 *
 * El token se guarda en localStorage porque nadie quiere pegarlo cada vez.
 * Si el backend lo rechaza, se borra y se vuelve a la pantalla de entrada.
 */
import { useState } from 'react'
import { Agenda } from './componentes/Agenda'
import { Clientes } from './componentes/Clientes'
import { Cobros } from './componentes/Cobros'
import { Entrada } from './componentes/Entrada'
import { Panel } from './componentes/Panel'
import './App.css'

const CLAVE = 'parte-del-dia:token'

const SECCIONES = [
  { id: 'hoy', nombre: 'Hoy', icono: '☰' },
  { id: 'agenda', nombre: 'Agenda', icono: '▤' },
  { id: 'cobros', nombre: 'Cobros', icono: '€' },
  { id: 'clientes', nombre: 'Clientes', icono: '☺' },
] as const

type Seccion = (typeof SECCIONES)[number]['id']

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(CLAVE) ?? '')
  const [error, setError] = useState('')
  const [seccion, setSeccion] = useState<Seccion>('hoy')

  function entrar(nuevo: string) {
    localStorage.setItem(CLAVE, nuevo)
    setError('')
    setToken(nuevo)
  }

  function salir(motivo = '') {
    localStorage.removeItem(CLAVE)
    setError(motivo)
    setToken('')
    setSeccion('hoy')
  }

  if (!token) return <Entrada onEntrar={entrar} error={error} />

  const invalido = () => salir('Ese token ya no vale. Pide otro con /web en el bot.')

  return (
    <div className="app">
      <main className="panel">
        <header>
          <h1>Parte del día</h1>
          <button className="enlace" onClick={() => salir()}>
            Salir
          </button>
        </header>

        {seccion === 'hoy' && (
          <Panel token={token} onTokenInvalido={invalido} conCabecera={false} />
        )}
        {seccion === 'agenda' && <Agenda token={token} onTokenInvalido={invalido} />}
        {seccion === 'cobros' && <Cobros token={token} onTokenInvalido={invalido} />}
        {seccion === 'clientes' && <Clientes token={token} onTokenInvalido={invalido} />}
      </main>

      <nav className="barra">
        {SECCIONES.map((s) => (
          <button
            key={s.id}
            className={seccion === s.id ? 'activa' : ''}
            onClick={() => setSeccion(s.id)}
            aria-current={seccion === s.id ? 'page' : undefined}
          >
            <span className="icono" aria-hidden="true">
              {s.icono}
            </span>
            {s.nombre}
          </button>
        ))}
      </nav>
    </div>
  )
}
