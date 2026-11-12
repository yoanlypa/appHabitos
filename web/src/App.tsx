/**
 * El marco de la aplicación: decide qué pantalla toca y pone la navegación.
 *
 * En el móvil la barra va abajo a propósito: esto se usa con una mano, de
 * pie, en casa de un cliente, y abajo es donde llega el pulgar. Caben cinco
 * secciones; Clientes, el tema y salir van en el menú de arriba, que se usan
 * menos. En el ordenador todo eso es un menú lateral fijo y el contenido
 * aprovecha el ancho.
 *
 * La sección va en la dirección (`#/agenda`): así el botón de atrás del móvil
 * vuelve a la pantalla anterior en vez de cerrar la app, y se puede recargar
 * sin perder el sitio.
 *
 * El token se guarda en localStorage porque nadie quiere pegarlo cada vez.
 * Si el backend lo rechaza, se borra y se vuelve a la pantalla de entrada.
 *
 * Al abrir se pregunta a /salud si los datos se están guardando. Se perdieron
 * dos veces sin que nada avisara, y el backend ya lo sabía: solo faltaba que
 * lo dijera donde se mira. Si no se guardan, sale una franja roja arriba en
 * todas las pantallas, entrada incluida, y no se puede cerrar.
 */
import {
  CalendarDays,
  Flame,
  House,
  LogOut,
  BellRing,
  Menu,
  Monitor,
  Moon,
  SquareKanban,
  Sun,
  TriangleAlert,
  Users,
  Wallet,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { salud } from './api'
import { Agenda } from './componentes/Agenda'
import { Ajustes } from './componentes/Ajustes'
import { Clientes } from './componentes/Clientes'
import { Entrada } from './componentes/Entrada'
import { Finanzas } from './componentes/Finanzas'
import { Habitos } from './componentes/Habitos'
import { Inicio } from './componentes/Inicio'
import { Logo } from './componentes/Logo'
import { Notas } from './componentes/Notas'
import { Avisos } from './ui/Avisos'
import { confirmar } from './ui/avisos'
import { useTema, type Tema } from './ui/ganchos'
import { Modal } from './ui/Modal'
import { SECCIONES, type Seccion } from './secciones'

const CLAVE = 'parte-del-dia:token'

const ICONOS = {
  inicio: House,
  notas: SquareKanban,
  agenda: CalendarDays,
  finanzas: Wallet,
  habitos: Flame,
  clientes: Users,
} as const

const TEMAS = [
  { id: 'claro', nombre: 'Claro', icono: Sun },
  { id: 'oscuro', nombre: 'Oscuro', icono: Moon },
  { id: 'sistema', nombre: 'Como el sistema', icono: Monitor },
] as const

/**
 * El botón "Abrir la web" de /web trae el token en la dirección
 * (`#token=...`): se guarda y se borra de la barra enseguida, para que no se
 * quede en el historial ni salga si se comparte el enlace.
 */
function tokenInicial(): string {
  const enlace = new URLSearchParams(window.location.hash.slice(1)).get('token')?.trim()
  if (enlace) {
    try {
      localStorage.setItem(CLAVE, enlace)
    } catch {
      /* sin almacenamiento sigue valiendo para esta visita */
    }
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    return enlace
  }
  try {
    return localStorage.getItem(CLAVE) ?? ''
  } catch {
    return ''
  }
}

function seccionDeLaDireccion(): Seccion {
  const id = window.location.hash.replace(/^#\/?/, '')
  return SECCIONES.find((s) => s.id === id)?.id ?? 'inicio'
}

function SelectorDeTema({ tema, onCambio }: { tema: Tema; onCambio: (t: Tema) => void }) {
  return (
    <div className="selector-tema" role="radiogroup" aria-label="Tema">
      {TEMAS.map(({ id, nombre, icono: Icono }) => (
        <button
          key={id}
          role="radio"
          aria-checked={tema === id}
          className={tema === id ? 'activa' : ''}
          title={nombre}
          aria-label={nombre}
          onClick={() => onCambio(id)}
        >
          <Icono size={16} />
        </button>
      ))}
    </div>
  )
}

export default function App() {
  const [token, setToken] = useState(tokenInicial)
  const [error, setError] = useState('')
  const [seccion, setSeccion] = useState<Seccion>(seccionDeLaDireccion)
  // El día que tiene que enseñar la agenda al llegar desde otra pantalla.
  const [diaAgenda, setDiaAgenda] = useState<string | undefined>(undefined)
  const [alarma, setAlarma] = useState('')
  const [menu, setMenu] = useState(false)
  const [ajustes, setAjustes] = useState(false)
  const [tema, setTema] = useTema()

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

  useEffect(() => {
    const alCambiar = () => setSeccion(seccionDeLaDireccion())
    window.addEventListener('hashchange', alCambiar)
    return () => window.removeEventListener('hashchange', alCambiar)
  }, [])

  const ir = useCallback((destino: Seccion, dia?: string) => {
    setDiaAgenda(destino === 'agenda' ? dia : undefined)
    setMenu(false)
    setSeccion(destino)
    if (seccionDeLaDireccion() !== destino) window.location.hash = `/${destino}`
    window.scrollTo(0, 0)
  }, [])

  function entrar(nuevo: string) {
    localStorage.setItem(CLAVE, nuevo)
    setError('')
    setToken(nuevo)
  }

  const salir = useCallback((motivo = '') => {
    localStorage.removeItem(CLAVE)
    setError(motivo)
    setToken('')
    setMenu(false)
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    setSeccion('inicio')
  }, [])

  const invalido = useCallback(
    () => salir('Ese token ya no vale. Pide otro con /web en el bot.'),
    [salir],
  )

  async function pedirSalir() {
    const si = await confirmar({
      titulo: '¿Cerrar la sesión?',
      texto: 'Para volver a entrar tendrás que pedirle otro enlace al bot con /web.',
      aceptar: 'Salir',
    })
    if (si) salir()
  }

  const franja = alarma && (
    <div className="alarma" role="alert">
      <TriangleAlert size={20} />
      <div>
        <strong>Los datos no se están guardando.</strong> Lo que apuntes se borrará en el próximo
        despliegue.
        <small>{alarma}</small>
      </div>
    </div>
  )

  if (!token)
    return (
      <>
        {franja}
        <Entrada onEntrar={entrar} error={error} />
      </>
    )

  const comunes = { token, onTokenInvalido: invalido }

  return (
    <div className="app">
      {franja}

      <div className="marco">
        <aside className="lateral">
          <div className="marca-app">
            <Logo />
            Parte del día
          </div>

          <nav aria-label="Secciones">
            {SECCIONES.map((s) => {
              const Icono = ICONOS[s.id]
              return (
                <button
                  key={s.id}
                  className={seccion === s.id ? 'nav-item activa' : 'nav-item'}
                  aria-current={seccion === s.id ? 'page' : undefined}
                  onClick={() => ir(s.id)}
                >
                  <Icono size={18} />
                  {s.nombre}
                </button>
              )
            })}
          </nav>

          <div className="lateral-pie">
            <button className="nav-item" onClick={() => setAjustes(true)}>
              <BellRing size={18} />
              Avisos
            </button>
            <SelectorDeTema tema={tema} onCambio={setTema} />
            <button className="nav-item" onClick={() => void pedirSalir()}>
              <LogOut size={18} />
              Salir
            </button>
          </div>
        </aside>

        <header className="barra-arriba">
          <div className="marca-app">
            <Logo />
            Parte del día
          </div>
          <button className="boton-icono" onClick={() => setMenu(true)} aria-label="Menú">
            <Menu size={22} />
          </button>
        </header>

        <main className="contenido">
          <div className={`pagina pagina-${seccion}`}>
            {seccion === 'inicio' && <Inicio {...comunes} onIr={ir} />}
            {seccion === 'notas' && <Notas {...comunes} onIr={ir} />}
            {seccion === 'agenda' && <Agenda key={diaAgenda} {...comunes} diaInicial={diaAgenda} />}
            {seccion === 'finanzas' && <Finanzas {...comunes} />}
            {seccion === 'habitos' && <Habitos {...comunes} />}
            {seccion === 'clientes' && <Clientes {...comunes} />}
          </div>
        </main>
      </div>

      <nav className="barra" aria-label="Secciones">
        {SECCIONES.slice(0, 5).map((s) => {
          const Icono = ICONOS[s.id]
          return (
            <button
              key={s.id}
              className={seccion === s.id ? 'activa' : ''}
              aria-current={seccion === s.id ? 'page' : undefined}
              onClick={() => ir(s.id)}
            >
              <Icono size={22} strokeWidth={seccion === s.id ? 2.4 : 1.9} />
              {s.nombre}
            </button>
          )
        })}
      </nav>

      {menu && (
        <Modal titulo="Menú" onCerrar={() => setMenu(false)} estrecha>
          <div className="menu-movil">
            <button className="nav-item" onClick={() => ir('clientes')}>
              <Users size={20} />
              Clientes
            </button>
            <div className="menu-tema">
              <span>Tema</span>
              <SelectorDeTema tema={tema} onCambio={setTema} />
            </div>
            <button
              className="nav-item"
              onClick={() => {
                setMenu(false)
                setAjustes(true)
              }}
            >
              <BellRing size={20} />
              Avisos
            </button>
            <button className="nav-item" onClick={() => void pedirSalir()}>
              <LogOut size={20} />
              Salir
            </button>
          </div>
        </Modal>
      )}

      {ajustes && (
        <Ajustes token={token} onTokenInvalido={invalido} onCerrar={() => setAjustes(false)} />
      )}

      <Avisos />
    </div>
  )
}
