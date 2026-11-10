/**
 * La ventana de todos los formularios.
 *
 * En el móvil sube desde abajo, donde llega el pulgar; en el ordenador sale
 * centrada. Se cierra con Escape, con la x y tocando fuera, salvo que se pida
 * lo contrario (`cierreFacil={false}`): en el escáner, tocar fuera sin querer
 * tiraría una lectura del ticket que ya se ha pagado.
 */
import { X } from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type Props = {
  titulo: string
  onCerrar: () => void
  children: ReactNode
  estrecha?: boolean
  cierreFacil?: boolean
}

export function Modal({ titulo, onCerrar, children, estrecha, cierreFacil = true }: Props) {
  // Guardado en una ref para que el efecto no se monte de nuevo en cada
  // pintado: `onCerrar` suele ser una función recién creada.
  const cerrar = useRef(onCerrar)
  useEffect(() => {
    cerrar.current = onCerrar
  })

  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      if (e.key === 'Escape') cerrar.current()
    }
    document.addEventListener('keydown', tecla)
    // Que no se mueva la página de detrás mientras se rellena el formulario.
    const antes = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', tecla)
      document.body.style.overflow = antes
    }
  }, [])

  return createPortal(
    <div
      className="modal-fondo"
      onMouseDown={(e) => {
        if (cierreFacil && e.target === e.currentTarget) onCerrar()
      }}
    >
      <div
        className={estrecha ? 'modal estrecha' : 'modal'}
        role="dialog"
        aria-modal="true"
        aria-label={titulo}
      >
        <header className="modal-cabecera">
          <h2>{titulo}</h2>
          <button type="button" className="boton-icono" onClick={onCerrar} aria-label="Cerrar">
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>,
    document.body,
  )
}
