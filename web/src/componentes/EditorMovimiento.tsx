/**
 * El formulario de un movimiento ya conectado a la API.
 *
 * Inicio, Finanzas, la gestoría y la ficha de un trabajo abren el mismo
 * formulario y hacen lo mismo con él (guardar solo lo que cambió, borrar,
 * recargar), así que eso vive aquí una vez.
 */
import type { Apunte, DatosMovimiento } from '../api'
import { borrarMovimiento, guardarMovimiento } from '../movimientos'
import { FormMovimiento } from './FormMovimiento'

type Props = {
  token: string
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  tipoInicial?: 'trabajo' | 'gasto'
  /** Para uno nuevo que ya se sabe de qué trabajo es. */
  trabajoInicial?: number | null
  /** Algo se ha guardado o borrado: quien lo abre recarga sus datos. */
  onCambio: () => void
  onCerrar: () => void
}

export function EditorMovimiento({
  token,
  apunte,
  tipoInicial,
  trabajoInicial,
  onCambio,
  onCerrar,
}: Props) {
  async function guardar(datos: DatosMovimiento) {
    await guardarMovimiento(token, apunte, datos)
    onCambio()
    onCerrar()
  }

  async function borrar() {
    if (!apunte) return
    await borrarMovimiento(token, apunte.id)
    onCambio()
    onCerrar()
  }

  return (
    <FormMovimiento
      token={token}
      apunte={apunte}
      tipoInicial={tipoInicial}
      trabajoInicial={trabajoInicial}
      onGuardar={guardar}
      onBorrar={apunte ? borrar : undefined}
      onCerrar={onCerrar}
    />
  )
}
