/**
 * El formulario de un movimiento ya conectado a la API.
 *
 * Inicio, Finanzas y la vista de la gestoría abren el mismo formulario y
 * hacen lo mismo con él (guardar solo lo que cambió, borrar, recargar), así
 * que eso vive aquí una vez. También el paso de "añadir un gasto a este
 * trabajo": se cierra el trabajo y se abre un gasto nuevo que ya sabe de
 * cuál es.
 */
import { useState } from 'react'
import type { Apunte, DatosMovimiento } from '../api'
import { borrarMovimiento, guardarMovimiento } from '../movimientos'
import { FormMovimiento } from './FormMovimiento'

type Props = {
  token: string
  /** El apunte a editar, o null para uno nuevo. */
  apunte: Apunte | null
  tipoInicial?: 'trabajo' | 'gasto'
  /** Algo se ha guardado o borrado: quien lo abre recarga sus datos. */
  onCambio: () => void
  onCerrar: () => void
}

export function EditorMovimiento({ token, apunte, tipoInicial, onCambio, onCerrar }: Props) {
  // Lo que hay abierto ahora: empieza por lo que se pidió y puede pasar a ser
  // un gasto nuevo para un trabajo.
  const [abierto, setAbierto] = useState<{ apunte: Apunte | null; deTrabajo: number | null }>({
    apunte,
    deTrabajo: null,
  })

  async function guardar(datos: DatosMovimiento) {
    await guardarMovimiento(token, abierto.apunte, datos)
    onCambio()
    onCerrar()
  }

  async function borrar() {
    if (!abierto.apunte) return
    await borrarMovimiento(token, abierto.apunte.id)
    onCambio()
    onCerrar()
  }

  return (
    <FormMovimiento
      // Otra clave, otro formulario: el gasto nuevo no hereda lo escrito en el trabajo.
      key={abierto.apunte?.id ?? `nuevo-${abierto.deTrabajo}`}
      token={token}
      apunte={abierto.apunte}
      tipoInicial={abierto.deTrabajo !== null ? 'gasto' : tipoInicial}
      trabajoInicial={abierto.deTrabajo}
      onGuardar={guardar}
      onBorrar={abierto.apunte ? borrar : undefined}
      onAnadirGasto={(trabajo) => setAbierto({ apunte: null, deTrabajo: trabajo.id })}
      onCerrar={onCerrar}
    />
  )
}
