/**
 * Meter varios movimientos de golpe: pegados (uno por línea), un CSV o
 * Excel del banco, o la captura de un historial de pagos.
 *
 * Es lo mismo que hace el bot (`servicios/importacion.py`), con las mismas
 * reglas: se enseña todo antes y entra al confirmar, lo que parece estar ya
 * (mismo día, tipo e importe) sale desmarcado pero se puede meter igual, y
 * una tabla que no dice si son gastos o cobros lo pregunta. Al acabar hay
 * un "Deshacer" que quita solo lo recién importado.
 *
 * No suma ni decide nada: lee lo que devuelve el backend y manda lo elegido.
 */
import { FileUp, Undo2 } from 'lucide-react'
import { useRef, useState } from 'react'
import {
  confirmarImportacion,
  deshacerImportacion,
  ErrorDeApi,
  leerImportacion,
  revisarImportacion,
  type MovimientoImportado,
} from '../api'
import { Modal } from '../ui/Modal'
import { ErrorEnLinea } from '../ui/piezas'
import { Segmentado } from '../ui/Segmentado'
import { euros, fechaCorta } from '../utiles'

type Props = {
  token: string
  onGuardado: () => void
  onError: (e: unknown) => void
  onCerrar: () => void
}

type Paso = 'entrada' | 'revision' | 'hecho'

const TIPOS = [
  { id: 'gasto', nombre: 'Son gastos' },
  { id: 'trabajo', nombre: 'Son cobros' },
] as const

const EJEMPLO = 'ayer -45 gasolina\n3/11 parking 2,75\nCambio de grifo Ana 120'

export function ImportarMovimientos({ token, onGuardado, onError, onCerrar }: Props) {
  const entradaFichero = useRef<HTMLInputElement>(null)
  const [paso, setPaso] = useState<Paso>('entrada')
  const [texto, setTexto] = useState('')
  const [movs, setMovs] = useState<MovimientoImportado[]>([])
  const [elegidos, setElegidos] = useState<boolean[]>([])
  const [faltaTipo, setFaltaTipo] = useState(false)
  // Lo leído tal cual, sin tipo: para poder cambiar de "gastos" a "cobros"
  // después de haber elegido (con el tipo ya puesto no se cambiaría).
  const [sinTipo, setSinTipo] = useState<MovimientoImportado[] | null>(null)
  const [tipo, setTipo] = useState<'gasto' | 'trabajo' | null>(null)
  const [hechos, setHechos] = useState<number[]>([])
  const [yaEstaban, setYaEstaban] = useState(0)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  async function hacer(accion: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await accion()
    } catch (e) {
      if (e instanceof ErrorDeApi) setError(e.message)
      else onError(e)
    } finally {
      setOcupado(false)
    }
  }

  function mostrar(lectura: { movimientos: MovimientoImportado[]; falta_tipo: boolean }) {
    setMovs(lectura.movimientos)
    // Lo que parece estar ya sale sin marcar: se ve, y se marca si de verdad son dos.
    setElegidos(lectura.movimientos.map((m) => !m.repetido))
    setFaltaTipo(lectura.falta_tipo)
    setPaso('revision')
  }

  function leer(fichero?: File) {
    void hacer(async () => {
      const lectura = await leerImportacion(token, fichero ? { fichero } : { texto })
      setSinTipo(lectura.falta_tipo ? lectura.movimientos : null)
      setTipo(null)
      mostrar(lectura)
    })
  }

  function elegirTipo(nuevo: 'gasto' | 'trabajo') {
    if (!sinTipo) return
    setTipo(nuevo)
    void hacer(async () => {
      mostrar(await revisarImportacion(token, sinTipo, nuevo))
    })
  }

  const cuantos = elegidos.filter(Boolean).length
  // Si se ha marcado a mano alguno de los que parecían repetidos, entra
  // exactamente lo elegido; si no, el backend vuelve a mirar qué está ya.
  const todo = movs.some((m, i) => m.repetido && elegidos[i])

  function anadir() {
    void hacer(async () => {
      const lista = movs.filter((_, i) => elegidos[i])
      const hecho = await confirmarImportacion(token, lista, todo)
      setHechos(hecho.apuntes.map((a) => a.id))
      setYaEstaban(hecho.ya_estaban)
      setPaso('hecho')
      onGuardado()
    })
  }

  function deshacer() {
    void hacer(async () => {
      await deshacerImportacion(token, hechos)
      setHechos([])
      onGuardado()
      onCerrar()
    })
  }

  return (
    // Con una captura ya leída (y pagada), tocar fuera sin querer no puede tirarla.
    <Modal titulo="Importar movimientos" onCerrar={onCerrar} cierreFacil={paso === 'entrada'}>
      {paso === 'entrada' && (
        <div className="formulario">
          <p className="ayuda">
            Pega un movimiento por línea, con la misma forma que en la caja de anotar. O sube el
            CSV o Excel del banco (columnas fecha, concepto e importe) o la captura de un
            historial de pagos.
          </p>
          <label className="campo">
            Movimientos
            <textarea
              rows={6}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder={EJEMPLO}
              autoFocus
            />
          </label>
          <input
            ref={entradaFichero}
            type="file"
            accept=".csv,.txt,.xlsx,image/*"
            hidden
            onChange={(e) => {
              const fichero = e.target.files?.[0]
              e.target.value = ''
              if (fichero) leer(fichero)
            }}
          />
          <ErrorEnLinea>{error}</ErrorEnLinea>
          <div className="botones">
            <button
              type="button"
              className="boton secundario"
              onClick={() => entradaFichero.current?.click()}
              disabled={ocupado}
            >
              <FileUp size={18} />
              Subir fichero o captura
            </button>
            <span className="derecha">
              <button
                type="button"
                className="boton"
                onClick={() => leer()}
                disabled={ocupado || !texto.trim()}
              >
                {ocupado ? 'Leyendo…' : 'Leer'}
              </button>
            </span>
          </div>
        </div>
      )}

      {paso === 'revision' && (
        <div className="formulario">
          {sinTipo ? (
            <>
              <p className="ayuda">No dice si entran o salen. ¿Qué son?</p>
              <Segmentado
                opciones={TIPOS}
                valor={tipo ?? ('' as 'gasto')}
                onCambio={elegirTipo}
                ancho
                etiqueta="Tipo"
              />
            </>
          ) : (
            <p className="ayuda">
              Esto es lo que he leído. Quita lo que no quieras y añade el resto.
            </p>
          )}

          <ul className="lista-importar">
            {movs.map((m, i) => (
              <li key={i} className={m.repetido ? 'repetido' : ''}>
                <label className="casilla">
                  <input
                    type="checkbox"
                    checked={elegidos[i] ?? false}
                    disabled={m.tipo === null}
                    onChange={(e) =>
                      setElegidos((antes) => antes.map((v, j) => (j === i ? e.target.checked : v)))
                    }
                  />
                  <span className="importar-fecha">{fechaCorta(m.fecha)}</span>
                  <span className="importar-concepto">
                    {m.concepto}
                    {m.repetido && <small>Parece que ya está</small>}
                    {m.pendiente && <small>Sin cobrar</small>}
                  </span>
                  <span className={`importar-importe ${m.tipo ?? ''}`}>
                    {m.tipo === 'gasto' ? '−' : m.tipo === 'trabajo' ? '+' : ''}
                    {euros(m.importe)}
                  </span>
                </label>
              </li>
            ))}
          </ul>

          <ErrorEnLinea>{error}</ErrorEnLinea>
          <div className="botones">
            <button type="button" className="boton secundario" onClick={() => setPaso('entrada')} disabled={ocupado}>
              Volver
            </button>
            <span className="derecha">
              <button
                type="button"
                className="boton"
                onClick={anadir}
                disabled={ocupado || cuantos === 0 || faltaTipo}
              >
                {ocupado ? 'Añadiendo…' : `Añadir ${cuantos}`}
              </button>
            </span>
          </div>
        </div>
      )}

      {paso === 'hecho' && (
        <div className="formulario">
          <p className="ayuda">
            {hechos.length === 0
              ? 'No ha entrado nada: ya estaba todo.'
              : `Añadido${hechos.length === 1 ? '' : 's'} ${hechos.length} movimiento${hechos.length === 1 ? '' : 's'}.`}
            {yaEstaban > 0 && ` ${yaEstaban} ya estaba${yaEstaban === 1 ? '' : 'n'} y no los he repetido.`}
          </p>
          <ErrorEnLinea>{error}</ErrorEnLinea>
          <div className="botones">
            {hechos.length > 0 && (
              <button type="button" className="boton secundario" onClick={deshacer} disabled={ocupado}>
                <Undo2 size={18} />
                Deshacer
              </button>
            )}
            <span className="derecha">
              <button type="button" className="boton" onClick={onCerrar}>
                Listo
              </button>
            </span>
          </div>
        </div>
      )}
    </Modal>
  )
}
