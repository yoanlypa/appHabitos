/**
 * La caja de anotar: una línea de texto y se acabó.
 *
 * Usa la misma sintaxis que el bot a propósito — quien apunta desde el móvil
 * por Telegram no tiene que aprender otra forma de escribir aquí. Lo que no
 * lleve importe se guarda como nota, igual que allí.
 *
 * Al anotar se dice siempre qué se ha entendido ("Gasto · gasolina · 45 €"):
 * si se interpretó un 120 donde se quiso poner 20, hay que verlo en el
 * momento y no al cuadrar el mes.
 */
import { CornerDownLeft, PenLine } from 'lucide-react'
import { useState } from 'react'
import { asignarCliente, crearApunte, type ApunteCreado } from '../api'
import { avisar } from '../ui/avisos'
import { describir } from '../utiles'
import { EscanerFactura } from './EscanerFactura'

type Props = {
  token: string
  /** Algo se ha anotado o cambiado: quien la usa recarga sus datos. */
  onCambio: () => void
  onFallo: (e: unknown) => void
}

export function Captura({ token, onCambio, onFallo }: Props) {
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [duda, setDuda] = useState<ApunteCreado | null>(null)

  async function anotar(e: React.FormEvent) {
    e.preventDefault()
    const limpio = texto.trim()
    if (!limpio || enviando) return
    setEnviando(true)
    try {
      const creado = await crearApunte(token, limpio)
      setTexto('')
      avisar(describir(creado.apunte))
      // Dos clientes con ese nombre: preguntamos en vez de adivinar, igual
      // que hace el bot. Colgarlo de la Ana equivocada sería peor.
      setDuda(creado.candidatos.length > 1 ? creado : null)
      onCambio()
    } catch (err) {
      onFallo(err)
    } finally {
      setEnviando(false)
    }
  }

  async function resolverDuda(clienteId: number | null) {
    if (!duda) return
    const apunteId = duda.apunte.id
    setDuda(null)
    try {
      await asignarCliente(token, apunteId, clienteId)
      onCambio()
    } catch (err) {
      onFallo(err)
    }
  }

  return (
    <section className="tarjeta captura">
      <form onSubmit={anotar}>
        <PenLine size={20} className="captura-icono" />
        <input
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Anota un trabajo, un gasto o una nota…"
          aria-label="Nuevo apunte"
          enterKeyHint="send"
        />
        <button type="submit" className="boton" disabled={!texto.trim() || enviando}>
          Anotar
          <CornerDownLeft size={16} />
        </button>
      </form>

      <div className="captura-pie">
        <ul className="pistas" aria-label="Cómo se escribe">
          <li>
            <code>Cambio de grifo Ana 120</code> <span>cobrado</span>
          </li>
          <li>
            <code>pendiente Reforma baño 980</code> <span>sin cobrar</span>
          </li>
          <li>
            <code>-45 gasolina</code> <span>gasto</span>
          </li>
          <li>
            <code>Llamar a Ana</code> <span>sin importe, nota</span>
          </li>
        </ul>
        <EscanerFactura token={token} onGuardado={onCambio} onError={onFallo} />
      </div>

      {duda && (
        <div className="duda">
          <p>
            ¿Qué <strong>{duda.candidatos[0].nombre.split(' ')[0]}</strong> es «
            {duda.apunte.concepto}»?
          </p>
          <div className="opciones">
            {duda.candidatos.map((c) => (
              <button
                key={c.id}
                className="boton secundario pequeno"
                onClick={() => void resolverDuda(c.id)}
              >
                {c.nombre}
                {c.telefono || c.direccion ? ` · ${c.telefono ?? c.direccion}` : ''}
              </button>
            ))}
            <button className="enlace gris" onClick={() => void resolverDuda(null)}>
              Ninguna
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
