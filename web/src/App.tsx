/**
 * Decide qué pantalla toca y mantiene la navegación entre secciones.
 *
 * La barra va abajo a propósito: esto se usa con una mano, de pie, en casa
 * de un cliente, y abajo es donde llega el pulgar.
 *
 * El token se guarda en localStorage porque nadie quiere pegarlo cada vez.
 * Si el backend lo rechaza, se borra y se vuelve a la pantalla de entrada.
 *
 * Al abrir se pregunta a /salud si los datos se están guardando. Se perdieron
 * dos veces sin que nada avisara, y el backend ya lo sabía: solo faltaba que
 * lo dijera donde se mira. Si no se guardan, sale una franja roja arriba en
 * todas las pantallas, entrada incluida, y no se puede cerrar.
 */
import { useEffect, useState } from 'react'
import { salud } from './api'
import { Agenda } from './componentes/Agenda'
import { Clientes } from './componentes/Clientes'
import { Cobros } from './componentes/Cobros'
import { Entrada } from './componentes/Entrada'
import { Notas } from './componentes/Notas'
import { Panel } from './componentes/Panel'
import './App.css'

const CLAVE = 'parte-del-dia:token'

const SECCIONES = [
  { id: 'hoy', nombre: 'Hoy', icono: '☰' },
  { id: 'notas', nombre: 'Notas', icono: '✎' },
  { id: 'agenda', nombre: 'Agenda', icono: '▤' },
  { id: 'cobros', nombre: 'Cobros', icono: '€' },
  { id: 'clientes', nombre: 'Clientes', icono: '☺' },
] as const

type Seccion = (typeof SECCIONES)[number]['id']

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(CLAVE) ?? '')
  const [error, setError] = useState('')
  const [seccion, setSeccion] = useState<Seccion>('hoy')
  const [alarma, setAlarma] = useState('')

  useEffect(() => {
    let cancelado = false
    void salud().then((estado) => {
      if (cancelado || !estado || estado.datos.persistente) return
      setAlarma(estado.datos.aviso ?? 'La base de datos no está en un sitio que sobreviva.')
    })
    return () => {
      cancelado = true
    }
  }, [])

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

  const franja = alarma && (
    <div className="alarma" role="alert">
      <strong>Los datos no se están guardando.</strong> Lo que apuntes se borrará en el próximo
      despliegue.
      <small>{alarma}</small>
    </div>
  )

  if (!token)
    return (
      <>
        {franja}
        <Entrada onEntrar={entrar} error={error} />
      </>
    )

  const invalido = () => salir('Ese token ya no vale. Pide otro con /web en el bot.')

  return (
    <div className="app">
      {franja}
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
        {seccion === 'notas' && (
          <Notas
            token={token}
            onTokenInvalido={invalido}
            onAgendada={() => setSeccion('agenda')}
          />
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
