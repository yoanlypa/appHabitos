/** Lo que comparten las pantallas que editan trabajos y gastos. */
import { borrarApunte, crearMovimiento, editarApunte, type Apunte, type DatosMovimiento } from './api'

/**
 * De lo que trae el formulario, solo lo que ha cambiado.
 *
 * Mandar el formulario entero pasaría por la validación campos que nadie ha
 * tocado: un apunte antiguo se rechazaría por algo que no se quería cambiar.
 */
function soloCambios(antes: Apunte, datos: DatosMovimiento): Partial<DatosMovimiento> {
  const cambios: Partial<DatosMovimiento> = {}
  for (const clave of Object.keys(datos) as (keyof DatosMovimiento)[]) {
    const era = clave === 'importe' ? Number(antes.importe) : antes[clave]
    const es = clave === 'importe' ? Number(datos.importe) : datos[clave]
    if (era !== es) Object.assign(cambios, { [clave]: datos[clave] })
  }
  return cambios
}

/** Guarda lo del formulario: crea uno nuevo o manda solo lo que cambió. */
export async function guardarMovimiento(token: string, antes: Apunte | null, datos: DatosMovimiento) {
  if (!antes) {
    await crearMovimiento(token, datos)
    return
  }
  const cambios = soloCambios(antes, datos)
  if (Object.keys(cambios).length) await editarApunte(token, antes.id, cambios)
}

export { borrarApunte as borrarMovimiento }
