/**
 * El año mes a mes: lo cobrado frente a lo gastado.
 *
 * Contesta de un vistazo a lo que la lista no deja ver: qué meses fueron
 * buenos, cuáles flojos y si los gastos van acompasados. Los doce totales los
 * da el backend con la misma suma que el resumen (`/resumen/meses`); aquí
 * solo se convierten en alturas.
 *
 * Tocar un mes lo elige como periodo, así que el gráfico es también la forma
 * más rápida de ir a "marzo".
 *
 * Los dos colores no son el verde y el rojo del resto de la app: son un par
 * comprobado para que se distingan también con daltonismo. Y por si acaso,
 * la leyenda y la ficha de cada mes lo dicen con letras.
 */
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { resumenMeses, type ResumenDeMes } from '../api'
import { euros, iso, MESES } from '../utiles'

type Props = {
  token: string
  /** Sube cuando algo cambia fuera, para volver a pedir los totales. */
  recargas: number
  onFallo: (e: unknown) => void
  /** Al tocar un mes: su primer y su último día (o hoy, si es el mes en curso). */
  onMes: (desde: string, hasta: string) => void
}

const ENTEROS = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0, useGrouping: 'always' })

/** Un tope redondo para el eje y sus marcas: 0 · 500 · 1.000 · 1.500. */
function escala(maximo: number) {
  if (maximo <= 0) return { tope: 100, marcas: [0, 50, 100] }
  const bruto = maximo / 3
  const magnitud = 10 ** Math.floor(Math.log10(bruto))
  const normal = bruto / magnitud
  const paso = (normal <= 1 ? 1 : normal <= 2 ? 2 : normal <= 5 ? 5 : 10) * magnitud
  const tope = Math.ceil(maximo / paso) * paso
  const marcas: number[] = []
  for (let v = 0; v <= tope + paso / 2; v += paso) marcas.push(v)
  return { tope, marcas }
}

export function GraficoMeses({ token, recargas, onFallo, onMes }: Props) {
  const hoy = new Date()
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [meses, setMeses] = useState<ResumenDeMes[] | null>(null)
  const [activo, setActivo] = useState<number | null>(null)

  useEffect(() => {
    let cancelado = false
    resumenMeses(token, anio)
      .then((datos) => {
        if (!cancelado) setMeses(datos)
      })
      .catch((e) => {
        if (!cancelado) onFallo(e)
      })
    return () => {
      cancelado = true
    }
  }, [token, anio, recargas, onFallo])

  const maximo = Math.max(0, ...(meses ?? []).flatMap((m) => [Number(m.cobrado), Number(m.gastos)]))
  const { tope, marcas } = escala(maximo)
  const esteAnio = anio === hoy.getFullYear()
  const vacio = meses !== null && maximo === 0

  function altura(valor: string) {
    const n = Number(valor)
    // Lo que no es cero se ve siempre, aunque sea una raya.
    return n > 0 ? `max(2px, ${(n / tope) * 100}%)` : '0'
  }

  function elegir(mes: number) {
    const fin = new Date(anio, mes, 0)
    onMes(iso(new Date(anio, mes - 1, 1)), iso(fin > hoy ? hoy : fin))
  }

  return (
    <section className="tarjeta grafico">
      <div className="tarjeta-cabecera">
        <div>
          <h2>Mes a mes</h2>
          <div className="leyenda">
            <span>
              <i className="cobrado" /> Cobrado
            </span>
            <span>
              <i className="gastos" /> Gastos
            </span>
          </div>
        </div>
        <div className="grafico-anio">
          <button className="boton-icono" onClick={() => setAnio(anio - 1)} aria-label="Año anterior">
            <ChevronLeft size={18} />
          </button>
          <strong>{anio}</strong>
          <button
            className="boton-icono"
            onClick={() => setAnio(anio + 1)}
            disabled={esteAnio}
            aria-label="Año siguiente"
          >
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      <div className="grafico-lienzo" onMouseLeave={() => setActivo(null)}>
        <div className="grafico-eje" aria-hidden="true">
          {marcas.map((v) => (
            <span key={v} style={{ bottom: `${(v / tope) * 100}%` }}>
              <b>{ENTEROS.format(v)}</b>
            </span>
          ))}
        </div>

        <div className="grafico-meses">
          {(meses ?? MESES.map((_, i) => ({ mes: i + 1, cobrado: '0', gastos: '0', pendiente: '0', neto: '0' }))).map(
            (m, i) => {
              const futuro = esteAnio && m.mes > hoy.getMonth() + 1
              return (
                <button
                  key={m.mes}
                  className={activo === i ? 'grafico-mes activo' : 'grafico-mes'}
                  disabled={futuro}
                  onClick={() => elegir(m.mes)}
                  onMouseEnter={() => setActivo(i)}
                  onFocus={() => setActivo(i)}
                  onBlur={() => setActivo(null)}
                  aria-label={`${MESES[i]} ${anio}: cobrado ${euros(m.cobrado)}, gastos ${euros(m.gastos)}. Ver este mes.`}
                >
                  <span className="barras">
                    <i className="barra-mes cobrado" style={{ height: altura(m.cobrado) }} />
                    <i className="barra-mes gastos" style={{ height: altura(m.gastos) }} />
                  </span>
                  <span className="mes-nombre">{MESES[i].slice(0, 3)}</span>

                  {activo === i && !futuro && (
                    <span className={`ficha-mes ${i < 3 ? 'izquierda' : i > 8 ? 'derecha' : ''}`} role="tooltip">
                      <strong>
                        {MESES[i]} {anio}
                      </strong>
                      <span>
                        <i className="cobrado" /> Cobrado <b>{euros(m.cobrado)}</b>
                      </span>
                      <span>
                        <i className="gastos" /> Gastos <b>{euros(m.gastos)}</b>
                      </span>
                      <span className="linea">
                        Neto <b>{euros(m.neto)}</b>
                      </span>
                      {Number(m.pendiente) > 0 && (
                        <span>
                          Pendiente <b>{euros(m.pendiente)}</b>
                        </span>
                      )}
                    </span>
                  )}
                </button>
              )
            },
          )}
        </div>

        {vacio && <p className="grafico-vacio">Sin movimientos en {anio}</p>}
      </div>

      {/* Lo mismo en tabla, para quien no ve el gráfico. */}
      {meses && (
        <table className="solo-lectores">
          <caption>Cobrado y gastos por mes en {anio}</caption>
          <thead>
            <tr>
              <th>Mes</th>
              <th>Cobrado</th>
              <th>Gastos</th>
              <th>Neto</th>
            </tr>
          </thead>
          <tbody>
            {meses.map((m) => (
              <tr key={m.mes}>
                <th>{MESES[m.mes - 1]}</th>
                <td>{euros(m.cobrado)}</td>
                <td>{euros(m.gastos)}</td>
                <td>{euros(m.neto)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
