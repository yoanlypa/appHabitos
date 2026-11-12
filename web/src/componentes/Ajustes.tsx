/**
 * Los avisos: a qué correo se mandan también los recordatorios de las citas.
 *
 * Por Telegram llegan siempre (el día antes a las 21:00 y una hora antes ese
 * mismo día). El correo es aparte, y lleva un botón de prueba porque es la
 * única forma de saber que funciona antes de que haga falta: si la clave de
 * Resend falta o está mal, mejor enterarse hoy que el día de la cita.
 */
import { MailCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { guardarCorreo, leerAjustes, probarCorreo, TokenInvalido, type Ajustes as DatosAjustes } from '../api'
import { avisar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea, Esqueleto } from '../ui/piezas'

type Props = {
  token: string
  onTokenInvalido: () => void
  onCerrar: () => void
}

export function Ajustes({ token, onTokenInvalido, onCerrar }: Props) {
  const [ajustes, setAjustes] = useState<DatosAjustes | null>(null)
  const [correo, setCorreo] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelado = false
    leerAjustes(token)
      .then((a) => {
        if (cancelado) return
        setAjustes(a)
        setCorreo(a.correo ?? '')
      })
      .catch((e) => {
        if (cancelado) return
        if (e instanceof TokenInvalido) return onTokenInvalido()
        setError(e instanceof Error ? e.message : 'No se han podido leer los ajustes')
      })
    return () => {
      cancelado = true
    }
  }, [token, onTokenInvalido])

  async function hacer(accion: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await accion()
    } catch (e) {
      if (e instanceof TokenInvalido) return onTokenInvalido()
      setError(e instanceof Error ? e.message : 'Algo ha fallado')
    } finally {
      setOcupado(false)
    }
  }

  const cambiado = ajustes !== null && correo.trim().toLowerCase() !== (ajustes.correo ?? '')

  function guardar(e: React.FormEvent) {
    e.preventDefault()
    void hacer(async () => {
      const nuevo = await guardarCorreo(token, correo.trim() || null)
      setAjustes(nuevo)
      setCorreo(nuevo.correo ?? '')
      avisar(nuevo.correo ? `Avisos también a ${nuevo.correo}` : 'Avisos solo por Telegram')
    })
  }

  function prueba() {
    void hacer(async () => {
      const { enviado_a } = await probarCorreo(token)
      avisar(`Correo de prueba enviado a ${enviado_a}`)
    })
  }

  return (
    <Modal titulo="Avisos" onCerrar={onCerrar}>
      {!ajustes ? (
        error ? <ErrorEnLinea>{error}</ErrorEnLinea> : <Esqueleto />
      ) : (
        <form className="formulario" onSubmit={guardar}>
          <p className="ayuda">
            Por Telegram te aviso de tus citas la noche antes y una hora antes ese mismo día.
            Pon tu correo y te llegará también ahí.
          </p>
          <label className="campo">
            Correo para los avisos
            <input
              type="email"
              inputMode="email"
              autoComplete="email"
              value={correo}
              onChange={(e) => setCorreo(e.target.value)}
              placeholder="nombre@gmail.com"
            />
          </label>
          {!ajustes.correo_disponible && (
            <p className="aviso-linea">
              El servidor todavía no sabe mandar correos: falta la clave de Resend
              (RESEND_API_KEY) en Railway. Hasta entonces, solo por Telegram.
            </p>
          )}
          {!ajustes.avisos_activos && (
            <p className="aviso-linea">
              Tienes los avisos apagados. Actívalos en el bot con /avisos on.
            </p>
          )}
          <ErrorEnLinea>{error}</ErrorEnLinea>
          <div className="botones">
            <button
              type="button"
              className="boton secundario"
              onClick={prueba}
              disabled={ocupado || cambiado || !ajustes.correo || !ajustes.correo_disponible}
              title={cambiado ? 'Guarda primero el correo' : undefined}
            >
              <MailCheck size={17} />
              Mandar prueba
            </button>
            <span className="derecha">
              <button type="submit" className="boton" disabled={ocupado || !cambiado}>
                Guardar
              </button>
            </span>
          </div>
        </form>
      )}
    </Modal>
  )
}
