/** Ganchos pequeños que usan varias pantallas. */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

/**
 * Si la pantalla es ancha (ordenador, tableta tumbada).
 *
 * Casi todo lo resuelve el CSS; esto es solo para lo que cambia de
 * comportamiento y no de aspecto: el tablero de notas enseña las tres
 * columnas a la vez en el ordenador y una con pestañas en el móvil.
 */
export function useEscritorio() {
  return useSyncExternalStore(alCambiarElAncho, () => window.matchMedia(ANCHA).matches)
}

const ANCHA = '(min-width: 900px)'

function alCambiarElAncho(avisarA: () => void) {
  const medio = window.matchMedia(ANCHA)
  medio.addEventListener('change', avisarA)
  return () => medio.removeEventListener('change', avisarA)
}

export type Tema = 'sistema' | 'claro' | 'oscuro'
const CLAVE_TEMA = 'parte-del-dia:tema'

function temaGuardado(): Tema {
  try {
    const guardado = localStorage.getItem(CLAVE_TEMA)
    return guardado === 'claro' || guardado === 'oscuro' ? guardado : 'sistema'
  } catch {
    return 'sistema'
  }
}

/** Aplica el tema al documento. También lo llama `main.tsx` antes de pintar. */
export function aplicarTema(tema: Tema = temaGuardado()) {
  if (tema === 'sistema') delete document.documentElement.dataset.tema
  else document.documentElement.dataset.tema = tema
}

/** Claro, oscuro o lo que diga el sistema. Se recuerda en este dispositivo. */
export function useTema(): [Tema, (tema: Tema) => void] {
  const [tema, setTema] = useState<Tema>(temaGuardado)

  useEffect(() => aplicarTema(tema), [tema])

  const cambiar = useCallback((nuevo: Tema) => {
    try {
      if (nuevo === 'sistema') localStorage.removeItem(CLAVE_TEMA)
      else localStorage.setItem(CLAVE_TEMA, nuevo)
    } catch {
      /* sin almacenamiento vale para esta visita */
    }
    setTema(nuevo)
  }, [])

  return [tema, cambiar]
}
