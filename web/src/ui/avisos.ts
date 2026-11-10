/**
 * Los avisos que aparecen un momento y las preguntas de "¿seguro?".
 *
 * Viven fuera de React para que cualquier pantalla pueda llamarlos con una
 * función (`avisar`, `confirmar`) sin pasarse nada por props. `Avisos.tsx`
 * es quien los pinta, una sola vez, en lo alto de la aplicación.
 *
 * Sustituyen al `confirm()` del navegador: aquel no decía qué se iba a
 * perder con las letras de la app, y en el móvil salía con la dirección de
 * la web encima, que parece un error.
 */

export type Aviso = { id: number; texto: string; tipo: 'bien' | 'mal' }

export type Pregunta = {
  titulo: string
  texto?: string
  /** Lo que pone el botón que confirma. */
  aceptar?: string
  /** Para lo que no se puede deshacer: el botón sale en rojo. */
  peligro?: boolean
  responder: (si: boolean) => void
}

type Estado = { avisos: Aviso[]; pregunta: Pregunta | null }

let estado: Estado = { avisos: [], pregunta: null }
const oyentes = new Set<() => void>()
let siguiente = 1

function cambiar(nuevo: Estado) {
  estado = nuevo
  oyentes.forEach((avisarA) => avisarA())
}

export function suscribir(oyente: () => void) {
  oyentes.add(oyente)
  return () => {
    oyentes.delete(oyente)
  }
}

export function leer() {
  return estado
}

/** Un mensaje corto que se quita solo. */
export function avisar(texto: string, tipo: Aviso['tipo'] = 'bien') {
  const id = siguiente++
  // Como mucho tres a la vez: más es una pila que nadie lee.
  cambiar({ ...estado, avisos: [...estado.avisos.slice(-2), { id, texto, tipo }] })
  setTimeout(
    () => cambiar({ ...estado, avisos: estado.avisos.filter((a) => a.id !== id) }),
    tipo === 'mal' ? 6000 : 3500,
  )
}

/** Pregunta antes de algo que no tiene vuelta atrás. Resuelve a sí o no. */
export function confirmar(pregunta: Omit<Pregunta, 'responder'>): Promise<boolean> {
  return new Promise((resolver) => {
    // Si había otra sin contestar, cuenta como un no.
    estado.pregunta?.responder(false)
    cambiar({
      ...estado,
      pregunta: {
        ...pregunta,
        responder: (si) => {
          cambiar({ ...estado, pregunta: null })
          resolver(si)
        },
      },
    })
  })
}
