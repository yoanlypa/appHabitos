/** Pinta lo que haya en `avisos.ts`: los mensajes de abajo y la pregunta. */
import { CircleAlert, CircleCheck } from 'lucide-react'
import { useSyncExternalStore } from 'react'
import { leer, suscribir } from './avisos'
import { Modal } from './Modal'

export function Avisos() {
  const { avisos, pregunta } = useSyncExternalStore(suscribir, leer)

  return (
    <>
      <div className="avisos" aria-live="polite">
        {avisos.map((a) => (
          <div key={a.id} className={`aviso ${a.tipo}`} role="status">
            {a.tipo === 'mal' ? <CircleAlert size={18} /> : <CircleCheck size={18} />}
            <span>{a.texto}</span>
          </div>
        ))}
      </div>

      {pregunta && (
        <Modal titulo={pregunta.titulo} onCerrar={() => pregunta.responder(false)} estrecha>
          <div className="formulario">
            {pregunta.texto && <p className="ayuda">{pregunta.texto}</p>}
            <div className="botones">
              <span className="derecha">
                <button className="boton secundario" onClick={() => pregunta.responder(false)}>
                  Cancelar
                </button>
                <button
                  className={pregunta.peligro ? 'boton peligro' : 'boton'}
                  autoFocus
                  onClick={() => pregunta.responder(true)}
                >
                  {pregunta.aceptar ?? 'Aceptar'}
                </button>
              </span>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
