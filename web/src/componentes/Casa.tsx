/**
 * Casa: el dinero y la compra del hogar, compartidos con quien viva en él.
 *
 * Va aparte del negocio a propósito (sus propias tablas en el backend): un
 * gasto del súper no puede acabar nunca en el trimestre ni en la gestoría.
 *
 * Cuatro pestañas, de lo más frecuente a lo menos:
 * - **Gastos**: la caja de anotar con la misma forma de escribir que el bot
 *   ("45 súper"), el mes con su total, en qué se va y quién lo paga.
 * - **Compra**: la lista y la despensa son la misma cosa. Se tacha al
 *   comprar y pasa a "En casa"; "se acabó" la devuelve a la lista.
 * - **Cocinar**: lo que hay en casa se le da al modelo para pensar platos.
 * - **Personas**: quién está, el enlace para invitar y el nombre de cada uno.
 *
 * Nada se suma aquí: los totales los da el backend.
 */
import {
  Baby,
  Car,
  ChefHat,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  CornerDownLeft,
  Crown,
  Banknote,
  HeartPulse,
  type LucideIcon,
  Popcorn,
  Receipt,
  Shirt,
  ShoppingBasket,
  Sofa,
  Tag,
  Utensils,
  Plus,
  RotateCcw,
  ShoppingCart,
  Sparkles,
  Trash2,
  UserMinus,
  UserPlus,
  Wallet,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  type Cartera,
  cambiarPagoHabitual,
  carteras as pedirCarteras,
  contarCartera,
  meterEnCartera,
  anadirALista,
  anotarGastoCasa,
  borrarArticulo,
  borrarGastoCasa,
  cambiarArticulo,
  cambiarMiNombre,
  crearGastoCasa,
  crearInvitacion,
  editarGastoCasa,
  ErrorDeApi,
  gastosCasa,
  listaCompra,
  miCasa,
  pedirRecetas,
  quitarMiembro,
  resumenCasa,
  TokenInvalido,
  type Articulo,
  type GastoCasa,
  type MiCasa,
  type Receta,
  type ResumenCasa,
} from '../api'
import { avisar, confirmar } from '../ui/avisos'
import { Modal } from '../ui/Modal'
import { Segmentado } from '../ui/Segmentado'
import { Avatar, Cabecera, ErrorEnLinea, Esqueleto, Kpi, Vacio } from '../ui/piezas'
import { aImporte, diaRelativo, euros, iso, MESES } from '../utiles'

type Props = {
  token: string
  onTokenInvalido: () => void
}

type Pestana = 'gastos' | 'compra' | 'cocinar' | 'personas'

const PESTANAS = [
  { id: 'gastos', nombre: 'Gastos' },
  { id: 'compra', nombre: 'Compra' },
  { id: 'cocinar', nombre: 'Cocinar' },
  { id: 'personas', nombre: 'Personas' },
] as const

const ICONO_CATEGORIA: Record<string, LucideIcon> = {
  Súper: ShoppingBasket,
  Casa: Sofa,
  Facturas: Receipt,
  Salud: HeartPulse,
  Coche: Car,
  Niños: Baby,
  Ropa: Shirt,
  Ocio: Popcorn,
  'Comer fuera': Utensils,
  Otros: Tag,
}

function rangoDelMes(anio: number, mes: number) {
  const desde = iso(new Date(anio, mes, 1))
  const hoy = new Date()
  const ultimo = new Date(anio, mes + 1, 0)
  return { desde, hasta: iso(ultimo > hoy ? hoy : ultimo) }
}

export function Casa({ token, onTokenInvalido }: Props) {
  const [pestana, setPestana] = useState<Pestana>('gastos')
  const [casa, setCasa] = useState<MiCasa | null>(null)
  const [articulos, setArticulos] = useState<Articulo[]>([])
  const [error, setError] = useState('')

  const fallo = useCallback(
    (e: unknown) => {
      if (e instanceof TokenInvalido) onTokenInvalido()
      else setError(e instanceof Error ? e.message : 'Algo ha fallado')
    },
    [onTokenInvalido],
  )

  const cargarCasa = useCallback(() => {
    miCasa(token).then(setCasa, fallo)
  }, [token, fallo])

  const cargarLista = useCallback(() => {
    listaCompra(token).then(setArticulos, fallo)
  }, [token, fallo])

  useEffect(() => {
    cargarCasa()
    cargarLista()
  }, [cargarCasa, cargarLista])

  const faltan = articulos.filter((a) => !a.hay)

  return (
    <>
      <Cabecera
        titulo={casa?.solo_casa ? `Hola, ${casa.yo.nombre}` : 'Casa'}
        subtitulo="Lo de casa, aparte del trabajo y compartido"
      />
      <Segmentado
        opciones={PESTANAS.map((p) => (p.id === 'compra' ? { ...p, cuenta: faltan.length } : p))}
        valor={pestana}
        onCambio={setPestana}
        ancho
        etiqueta="Casa"
      />
      <ErrorEnLinea>{error}</ErrorEnLinea>
      {!casa ? (
        <Esqueleto />
      ) : (
        <div className="casa">
          {pestana === 'gastos' && <Gastos token={token} casa={casa} onFallo={fallo} />}
          {pestana === 'compra' && (
            <Compra token={token} articulos={articulos} onCambio={cargarLista} onFallo={fallo} />
          )}
          {pestana === 'cocinar' && (
            <Cocinar
              token={token}
              casa={casa}
              enCasa={articulos.filter((a) => a.hay)}
              onCambio={cargarLista}
              onFallo={fallo}
            />
          )}
          {pestana === 'personas' && (
            <Personas token={token} casa={casa} onCambio={cargarCasa} onFallo={fallo} />
          )}
        </div>
      )}
    </>
  )
}

// --- Gastos -------------------------------------------------------------------

type Hijo = { token: string; onFallo: (e: unknown) => void }

function Gastos({ token, casa, onFallo }: Hijo & { casa: MiCasa }) {
  const hoy = new Date()
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth())
  const [gastos, setGastos] = useState<GastoCasa[] | null>(null)
  const [resumen, setResumen] = useState<ResumenCasa | null>(null)
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [editando, setEditando] = useState<GastoCasa | 'nuevo' | null>(null)
  const [recargas, setRecargas] = useState(0)

  const { desde, hasta } = rangoDelMes(anio, mes)
  const esteMes = anio === hoy.getFullYear() && mes === hoy.getMonth()
  const nombres = new Map(casa.miembros.map((m) => [m.user_id, m.nombre]))
  const variasPersonas = casa.miembros.length > 1

  useEffect(() => {
    let vivo = true
    Promise.all([gastosCasa(token, desde, hasta), resumenCasa(token, desde, hasta)]).then(
      ([g, r]) => {
        if (!vivo) return
        setGastos(g)
        setResumen(r)
      },
      onFallo,
    )
    return () => {
      vivo = false
    }
  }, [token, desde, hasta, recargas, onFallo])

  const recargar = () => setRecargas((n) => n + 1)

  function moverMes(paso: number) {
    const d = new Date(anio, mes + paso, 1)
    if (d > hoy) return
    setAnio(d.getFullYear())
    setMes(d.getMonth())
  }

  async function anotar(e: React.FormEvent) {
    e.preventDefault()
    const limpio = texto.trim()
    if (!limpio || enviando) return
    setEnviando(true)
    try {
      const g = await anotarGastoCasa(token, limpio)
      setTexto('')
      avisar(`Gasto de casa · ${g.concepto} · ${euros(g.importe)} · ${g.categoria}`)
      if (!esteMes) {
        setAnio(hoy.getFullYear())
        setMes(hoy.getMonth())
      } else recargar()
    } catch (err) {
      if (err instanceof ErrorDeApi) avisar(err.message, 'mal')
      else onFallo(err)
    } finally {
      setEnviando(false)
    }
  }

  // Agrupados por día, como en Finanzas.
  const porDia = new Map<string, GastoCasa[]>()
  for (const g of gastos ?? []) porDia.set(g.fecha, [...(porDia.get(g.fecha) ?? []), g])
  const maxCategoria = Math.max(1, ...(resumen?.por_categoria.map((c) => Number(c.total)) ?? [1]))
  const diferencia = resumen ? Number(resumen.total) - Number(resumen.anterior) : 0

  return (
    <>
      <section className="tarjeta captura">
        <form onSubmit={anotar}>
          <Wallet size={20} className="captura-icono" />
          <input
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="45 súper, pagué 60 de luz…"
            aria-label="Nuevo gasto de casa"
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
              <code>45 súper</code> <span>hoy</span>
            </li>
            <li>
              <code>ayer 12,50 farmacia</code> <span>otro día</span>
            </li>
          </ul>
          <button className="boton suave pequeno" onClick={() => setEditando('nuevo')}>
            <Plus size={16} /> Con detalle
          </button>
        </div>
      </section>

      <div className="casa-mes">
        <button className="boton-icono" onClick={() => moverMes(-1)} aria-label="Mes anterior">
          <ChevronLeft size={20} />
        </button>
        <strong>
          {MESES[mes]} {anio !== hoy.getFullYear() ? anio : ''}
        </strong>
        <button
          className="boton-icono"
          onClick={() => moverMes(1)}
          disabled={esteMes}
          aria-label="Mes siguiente"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      {!resumen || !gastos ? (
        <Esqueleto />
      ) : (
        <>
          <dl className="kpis">
            <Kpi
              nombre={esteMes ? 'Gastado este mes' : 'Gastado'}
              valor={euros(resumen.total)}
              tipo="gasto"
              nota={
                Number(resumen.anterior) > 0
                  ? `${diferencia > 0 ? '+' : ''}${euros(diferencia)} que el periodo anterior`
                  : undefined
              }
            />
            {variasPersonas &&
              resumen.por_persona.map((p) => <Kpi key={p.nombre} nombre={p.nombre} valor={euros(p.total)} />)}
            {Number(resumen.efectivo) > 0 && (
              <Kpi
                nombre="En efectivo"
                valor={euros(resumen.efectivo)}
                nota={Number(resumen.sin_detallar) > 0 ? `${euros(resumen.sin_detallar)} sin detallar` : 'Todo detallado'}
              />
            )}
          </dl>

          <Carteras token={token} casa={casa} recargas={recargas} onCambio={recargar} onFallo={onFallo} />

          {resumen.por_categoria.length > 0 && (
            <section className="tarjeta">
              <div className="tarjeta-cabecera">
                <h2>En qué se va</h2>
              </div>
              <ul className="barras-casa">
                {resumen.por_categoria.map((c) => (
                  <li key={c.nombre}>
                    <span className="barras-nombre">{c.nombre}</span>
                    <span className="barras-pista">
                      <i style={{ width: `${(Number(c.total) / maxCategoria) * 100}%` }} />
                    </span>
                    <span className="barras-valor">{euros(c.total)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {gastos.length === 0 ? (
            <Vacio icono={Wallet} titulo="Nada gastado en este mes">
              Escribe arriba «45 súper», o mándaselo al bot.
            </Vacio>
          ) : (
            <section className="tarjeta movimientos">
              {[...porDia.entries()].map(([dia, lista]) => (
              <div key={dia} className="dia">
                <h3>{diaRelativo(dia)}</h3>
                <ul className="lista">
                  {lista.map((g) => {
                    const Icono = ICONO_CATEGORIA[g.categoria] ?? Tag
                    return (
                    <li key={g.id} className="fila movimiento tocable" onClick={() => setEditando(g)}>
                      <span className="insignia gasto">
                        <Icono size={18} />
                      </span>
                      <span className="principal">
                        {g.concepto}
                        <small>
                          {g.efectivo ? '💶 ' : '💳 '}
                          {g.categoria}
                          {variasPersonas && ` · ${nombres.get(g.user_id) ?? 'Otra persona'}`}
                        </small>
                      </span>
                      <span className="importe gasto">−{euros(g.importe)}</span>
                    </li>
                    )
                  })}
                </ul>
              </div>
              ))}
            </section>
          )}
        </>
      )}

      {editando && (
        <FormGastoCasa
          gasto={editando === 'nuevo' ? null : editando}
          casa={casa}
          onCerrar={() => setEditando(null)}
          onGuardar={async (datos) => {
            if (editando === 'nuevo') await crearGastoCasa(token, datos)
            else await editarGastoCasa(token, editando.id, datos)
            setEditando(null)
            recargar()
          }}
          onBorrar={
            editando === 'nuevo'
              ? undefined
              : async () => {
                  await borrarGastoCasa(token, editando.id)
                  setEditando(null)
                  recargar()
                }
          }
        />
      )}
    </>
  )
}

function FormGastoCasa({
  gasto,
  casa,
  onCerrar,
  onGuardar,
  onBorrar,
}: {
  gasto: GastoCasa | null
  casa: MiCasa
  onCerrar: () => void
  onGuardar: (datos: {
    concepto: string
    importe: string
    fecha: string
    categoria: string
    pagado_por: number
    efectivo: boolean
  }) => Promise<void>
  onBorrar?: () => Promise<void>
}) {
  const [concepto, setConcepto] = useState(gasto?.concepto ?? '')
  const [importe, setImporte] = useState(gasto ? gasto.importe.replace('.', ',') : '')
  const [fecha, setFecha] = useState(gasto?.fecha ?? iso(new Date()))
  const [categoria, setCategoria] = useState(gasto?.categoria ?? 'Otros')
  const [quien, setQuien] = useState(gasto?.user_id ?? casa.yo.user_id)
  const [efectivo, setEfectivo] = useState(gasto?.efectivo ?? casa.yo.efectivo)
  const [error, setError] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const limpio = aImporte(importe)

  async function hacer(accion: () => Promise<void>) {
    setOcupado(true)
    setError('')
    try {
      await accion()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se ha podido guardar')
      setOcupado(false)
    }
  }

  async function borrar() {
    if (!onBorrar || !gasto) return
    const si = await confirmar({
      titulo: `¿Borrar «${gasto.concepto}»?`,
      texto: 'Se quita de las cuentas de casa. No se puede deshacer.',
      aceptar: 'Borrar',
      peligro: true,
    })
    if (si) void hacer(onBorrar)
  }

  return (
    <Modal titulo={gasto ? 'Gasto de casa' : 'Nuevo gasto de casa'} onCerrar={onCerrar}>
      <form
        className="formulario"
        onSubmit={(e) => {
          e.preventDefault()
          if (!limpio || !concepto.trim()) return
          void hacer(() =>
            onGuardar({ concepto: concepto.trim(), importe: limpio, fecha, categoria, pagado_por: quien, efectivo }),
          )
        }}
      >
        <label className="campo">
          Concepto
          <input value={concepto} onChange={(e) => setConcepto(e.target.value)} placeholder="Mercadona" autoFocus={!gasto} />
        </label>
        <div className="dos-campos">
          <label className="campo">
            Importe (€)
            <input inputMode="decimal" value={importe} onChange={(e) => setImporte(e.target.value)} placeholder="45,50" />
          </label>
          <label className="campo">
            Fecha
            <input type="date" value={fecha} max={iso(new Date())} onChange={(e) => setFecha(e.target.value)} />
          </label>
        </div>
        <div className="dos-campos">
          <label className="campo">
            Categoría
            <select value={categoria} onChange={(e) => setCategoria(e.target.value)}>
              {casa.categorias.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          {casa.miembros.length > 1 && (
            <label className="campo">
              Lo pagó
              <select value={quien} onChange={(e) => setQuien(Number(e.target.value))}>
                {casa.miembros.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {m.nombre}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        <Segmentado
          opciones={[
            { id: 'efectivo', nombre: '💶 Efectivo' },
            { id: 'tarjeta', nombre: '💳 Tarjeta' },
          ]}
          valor={efectivo ? 'efectivo' : 'tarjeta'}
          onCambio={(v) => setEfectivo(v === 'efectivo')}
          ancho
          etiqueta="Cómo se pagó"
        />
        {importe && !limpio && <ErrorEnLinea>El importe no se entiende: escribe 45 o 45,50.</ErrorEnLinea>}
        <ErrorEnLinea>{error}</ErrorEnLinea>
        <div className="botones">
          {gasto && onBorrar && (
            <button
              type="button"
              className="boton-icono peligro"
              onClick={() => void borrar()}
              disabled={ocupado}
              aria-label="Borrar"
              title="Borrar"
            >
              <Trash2 size={18} />
            </button>
          )}
          <span className="derecha">
            <button type="button" className="boton secundario" onClick={onCerrar} disabled={ocupado}>
              Cancelar
            </button>
            <button type="submit" className="boton" disabled={!limpio || !concepto.trim() || ocupado}>
              {ocupado ? 'Guardando…' : 'Guardar'}
            </button>
          </span>
        </div>
      </form>
    </Modal>
  )
}

// --- Carteras -----------------------------------------------------------------

/**
 * El efectivo no deja rastro: se apunta lo que entra y se cuenta lo que queda.
 * La diferencia que nadie apuntó la anota el backend como "sin detallar".
 */
function Carteras({
  token,
  casa,
  recargas,
  onCambio,
  onFallo,
}: Hijo & { casa: MiCasa; recargas: number; onCambio: () => void }) {
  const [lista, setLista] = useState<Cartera[]>([])
  const [accion, setAccion] = useState<'entrada' | 'recuento' | null>(null)
  const [importe, setImporte] = useState('')
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    let vivo = true
    pedirCarteras(token).then((c) => vivo && setLista(c), onFallo)
    return () => {
      vivo = false
    }
  }, [token, recargas, onFallo])

  const mia = lista.find((c) => c.user_id === casa.yo.user_id)
  const limpio = aImporte(importe) ?? (importe.trim() === '0' ? '0' : null)

  function abrir(tipo: 'entrada' | 'recuento') {
    setImporte(tipo === 'recuento' && mia?.esperado && Number(mia.esperado) >= 0 ? mia.esperado.replace('.', ',') : '')
    setAccion(tipo)
  }

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    if (!limpio || !accion) return
    setOcupado(true)
    try {
      if (accion === 'entrada') {
        await meterEnCartera(token, limpio)
        avisar(`A tu cartera: +${euros(limpio)}`)
      } else {
        const r = await contarCartera(token, limpio)
        if (r.esperado === null) avisar(`Punto de partida: ${euros(r.contado)}`)
        else if (Number(r.sin_detallar) > 0) avisar(`Faltan ${euros(r.sin_detallar)}: anotados como efectivo sin detallar`)
        else if (Number(r.sobra) > 0) avisar(`Sobran ${euros(r.sobra)}: ¿entró dinero sin apuntar?`)
        else avisar('Cuadra al céntimo')
      }
      setAccion(null)
      onCambio()
    } catch (err) {
      onFallo(err)
    } finally {
      setOcupado(false)
    }
  }

  return (
    <section className="tarjeta">
      <div className="tarjeta-cabecera">
        <h2>
          <Banknote size={18} />
          Carteras
        </h2>
      </div>
      <ul className="lista">
        {lista.map((c) => (
          <li key={c.user_id} className="fila">
            <Avatar nombre={c.nombre} />
            <span className="principal">
              {c.nombre}
              <small>
                {c.contado_el
                  ? [
                      `Contada ${diaRelativo(c.contado_el).toLowerCase()}`,
                      Number(c.entradas) > 0 && `+${euros(c.entradas)} entrado`,
                      Number(c.gastado) > 0 && `−${euros(c.gastado)} apuntado`,
                    ]
                      .filter(Boolean)
                      .join(' · ')
                  : 'Sin contar todavía'}
              </small>
            </span>
            <span className="importe">{c.esperado !== null ? euros(c.esperado) : '—'}</span>
          </li>
        ))}
      </ul>
      <div className="botones cartera-botones">
        <button className="boton suave pequeno" onClick={() => abrir('entrada')}>
          <Plus size={16} /> Saqué dinero
        </button>
        <button className="boton pequeno" onClick={() => abrir('recuento')}>
          <Banknote size={16} /> Contar mi cartera
        </button>
      </div>
      <p className="ayuda">
        No hace falta apuntar cada billete: apunta lo que sacas y cuenta de vez en cuando. Lo que falte y nadie apuntó
        entra como «Efectivo sin detallar».
      </p>

      {accion && (
        <Modal
          titulo={accion === 'entrada' ? 'Dinero a tu cartera' : '¿Cuánto te queda?'}
          onCerrar={() => setAccion(null)}
          estrecha
        >
          <form className="formulario" onSubmit={guardar}>
            {accion === 'recuento' && (
              <p className="ayuda">
                {mia?.esperado != null
                  ? `Debería haber ${euros(mia.esperado)}. Cuenta los billetes y monedas y pon lo que hay.`
                  : 'Es la primera vez: lo que pongas será el punto de partida.'}
              </p>
            )}
            <label className="campo">
              {accion === 'entrada' ? 'Lo que has sacado o te han dado (€)' : 'Lo que hay ahora (€)'}
              <input inputMode="decimal" value={importe} onChange={(e) => setImporte(e.target.value)} autoFocus />
            </label>
            <div className="botones">
              <span className="derecha">
                <button type="button" className="boton secundario" onClick={() => setAccion(null)}>
                  Cancelar
                </button>
                <button type="submit" className="boton" disabled={!limpio || ocupado}>
                  {accion === 'entrada' ? 'Añadir' : 'Contado'}
                </button>
              </span>
            </div>
          </form>
        </Modal>
      )}
    </section>
  )
}

// --- Compra -------------------------------------------------------------------

function Compra({
  token,
  articulos,
  onCambio,
  onFallo,
}: Hijo & { articulos: Articulo[]; onCambio: () => void }) {
  const [texto, setTexto] = useState('')
  const faltan = articulos.filter((a) => !a.hay)
  const hay = articulos.filter((a) => a.hay)

  async function hacer(accion: () => Promise<unknown>) {
    try {
      await accion()
      onCambio()
    } catch (e) {
      onFallo(e)
    }
  }

  async function anadir(e: React.FormEvent) {
    e.preventDefault()
    const limpio = texto.trim()
    if (!limpio) return
    setTexto('')
    await hacer(() => anadirALista(token, limpio))
  }

  return (
    <>
      <section className="tarjeta captura">
        <form onSubmit={anadir}>
          <ShoppingCart size={20} className="captura-icono" />
          <input
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Leche, huevos y pan…"
            aria-label="Añadir a la lista"
            enterKeyHint="send"
          />
          <button type="submit" className="boton" disabled={!texto.trim()}>
            Añadir
          </button>
        </form>
      </section>

      <section className="tarjeta">
        <div className="tarjeta-cabecera">
          <h2>
            <ShoppingCart size={18} />
            Falta comprar
            {faltan.length > 0 && <span className="contador">{faltan.length}</span>}
          </h2>
        </div>
        {faltan.length === 0 ? (
          <Vacio titulo="No falta nada">Escribe arriba lo que se acabe, o díselo al bot.</Vacio>
        ) : (
          <ul className="lista">
            {faltan.map((a) => (
              <li key={a.id} className="fila">
                <button
                  className="marca"
                  aria-label={`Comprado: ${a.texto}`}
                  onClick={() => void hacer(() => cambiarArticulo(token, a.id, { hay: true }))}
                />
                <span className="principal">{a.texto}</span>
                <button
                  className="boton-icono"
                  aria-label={`Quitar ${a.texto}`}
                  title="Quitar de la lista"
                  onClick={() => void hacer(() => borrarArticulo(token, a.id))}
                >
                  <X size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="tarjeta">
        <div className="tarjeta-cabecera">
          <h2>En casa</h2>
        </div>
        {hay.length === 0 ? (
          <p className="ayuda">Lo que taches de la lista aparece aquí. Es lo que se usa para pensar qué cocinar.</p>
        ) : (
          <>
            <p className="ayuda">Toca lo que se acabe y vuelve a la lista.</p>
            <ul className="chips">
              {hay.map((a) => (
                <li key={a.id}>
                  <button
                    className="chip"
                    title="Se acabó: a la lista"
                    onClick={() => void hacer(() => cambiarArticulo(token, a.id, { hay: false }))}
                  >
                    {a.texto}
                    <RotateCcw size={13} />
                  </button>
                  <button
                    className="chip-quitar"
                    aria-label={`Quitar ${a.texto}`}
                    onClick={() => void hacer(() => borrarArticulo(token, a.id))}
                  >
                    <X size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  )
}

// --- Cocinar ------------------------------------------------------------------

function Cocinar({
  token,
  casa,
  enCasa,
  onCambio,
  onFallo,
}: Hijo & { casa: MiCasa; enCasa: Articulo[]; onCambio: () => void }) {
  const [preferencias, setPreferencias] = useState('')
  const [recetas, setRecetas] = useState<Receta[] | null>(null)
  const [pensando, setPensando] = useState(false)
  const [error, setError] = useState('')

  async function pensar(e: React.FormEvent) {
    e.preventDefault()
    setPensando(true)
    setError('')
    try {
      setRecetas(await pedirRecetas(token, preferencias))
    } catch (err) {
      if (err instanceof ErrorDeApi) setError(err.message)
      else onFallo(err)
    } finally {
      setPensando(false)
    }
  }

  async function aLaLista(cosas: string[]) {
    try {
      await anadirALista(token, cosas.join(', '))
      avisar(`A la lista: ${cosas.join(', ')}`)
      onCambio()
    } catch (err) {
      onFallo(err)
    }
  }

  if (!casa.hay_recetas)
    return (
      <Vacio icono={ChefHat} titulo="Las recetas aún no están activadas">
        Hace falta la clave de OpenAI en el servidor, la misma que la de las notas de voz.
      </Vacio>
    )

  return (
    <>
      <section className="tarjeta">
        <div className="tarjeta-cabecera">
          <h2>
            <ChefHat size={18} />
            ¿Qué hago de comer?
          </h2>
        </div>
        <p className="ayuda">
          {enCasa.length > 0
            ? `Con lo que hay en casa: ${enCasa.map((a) => a.texto.toLowerCase()).join(', ')}.`
            : 'Aún no hay nada marcado en casa. Escribe abajo lo que tengas.'}
        </p>
        <form className="formulario" onSubmit={pensar}>
          <label className="campo">
            Algo más que tengas, o cómo lo quieres
            <input
              value={preferencias}
              onChange={(e) => setPreferencias(e.target.value)}
              placeholder="pollo y arroz, rápido, para los niños, sin horno…"
            />
          </label>
          <ErrorEnLinea>{error}</ErrorEnLinea>
          <div className="botones">
            <span className="derecha">
              <button type="submit" className="boton" disabled={pensando || (!enCasa.length && !preferencias.trim())}>
                <Sparkles size={16} />
                {pensando ? 'Pensando…' : 'Darme ideas'}
              </button>
            </span>
          </div>
        </form>
      </section>

      {recetas?.length === 0 && <Vacio titulo="No se me ha ocurrido nada">Prueba a decir algo más que tengas.</Vacio>}
      {recetas?.map((r) => (
        <article key={r.nombre} className="tarjeta receta">
          <h3>
            {r.nombre}
            {r.minutos && (
              <small>
                <Clock size={14} /> {r.minutos} min
              </small>
            )}
          </h3>
          {r.usa.length > 0 && <p className="ayuda">Usa: {r.usa.join(', ')}</p>}
          {r.falta.length > 0 && (
            <p className="receta-falta">
              Faltaría: {r.falta.join(', ')}
              <button className="enlace" onClick={() => void aLaLista(r.falta)}>
                <Plus size={14} /> A la lista
              </button>
            </p>
          )}
          <ol>
            {r.pasos.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ol>
        </article>
      ))}
    </>
  )
}

// --- Personas -----------------------------------------------------------------

function Personas({ token, casa, onCambio, onFallo }: Hijo & { casa: MiCasa; onCambio: () => void }) {
  const [enlace, setEnlace] = useState<{ codigo: string; dias: number } | null>(null)
  const [nombre, setNombre] = useState(casa.yo.nombre)

  async function invitar() {
    try {
      setEnlace(await crearInvitacion(token))
    } catch (e) {
      onFallo(e)
    }
  }

  const url = enlace ? `${window.location.origin}${window.location.pathname}#invitacion=${enlace.codigo}` : ''

  async function copiar() {
    try {
      await navigator.clipboard.writeText(url)
      avisar('Enlace copiado')
    } catch {
      avisar('No se ha podido copiar: mantén pulsado el enlace', 'mal')
    }
  }

  async function guardarNombre(e: React.FormEvent) {
    e.preventDefault()
    if (!nombre.trim() || nombre.trim() === casa.yo.nombre) return
    try {
      await cambiarMiNombre(token, nombre.trim())
      avisar('Nombre cambiado')
      onCambio()
    } catch (err) {
      onFallo(err)
    }
  }

  async function quitar(id: number, quien: string) {
    const si = await confirmar({
      titulo: `¿Quitar a ${quien} de casa?`,
      texto: 'Lo que anotó se queda. Para volver necesitará otra invitación.',
      aceptar: 'Quitar',
      peligro: true,
    })
    if (!si) return
    try {
      await quitarMiembro(token, id)
      onCambio()
    } catch (e) {
      onFallo(e)
    }
  }

  return (
    <>
      <section className="tarjeta">
        <div className="tarjeta-cabecera">
          <h2>Quién está en casa</h2>
        </div>
        <ul className="lista">
          {casa.miembros.map((m) => (
            <li key={m.id} className="fila">
              <Avatar nombre={m.nombre} />
              <span className="principal">
                {m.nombre}
                {m.id === casa.yo.id && <small>tú</small>}
              </span>
              {m.titular && <Crown size={16} aria-label="Creó la casa" />}
              {casa.yo.titular && !m.titular && (
                <button className="boton-icono" aria-label={`Quitar a ${m.nombre}`} onClick={() => void quitar(m.id, m.nombre)}>
                  <UserMinus size={16} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {casa.yo.titular && (
        <section className="tarjeta">
          <div className="tarjeta-cabecera">
            <h2>
              <UserPlus size={18} />
              Invitar
            </h2>
          </div>
          <p className="ayuda">
            Quien entre podrá anotar gastos y la compra, desde esta web o por Telegram. Solo verá Casa: tus trabajos no.
          </p>
          {!enlace ? (
            <button className="boton" onClick={() => void invitar()}>
              <UserPlus size={16} /> Crear invitación
            </button>
          ) : (
            <div className="invitacion">
              <p>
                Mándale este enlace. Vale una vez y durante {enlace.dias} días:
              </p>
              <code className="invitacion-enlace">{url}</code>
              <div className="botones">
                <button className="boton" onClick={() => void copiar()}>
                  <Copy size={16} /> Copiar enlace
                </button>
                <a
                  className="boton secundario"
                  href={`https://wa.me/?text=${encodeURIComponent(`Para apuntar los gastos de casa conmigo: ${url}`)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  WhatsApp
                </a>
              </div>
              <p className="ayuda">
                Si usa Telegram, también puede escribirle al bot <code>/unirme {enlace.codigo}</code>.
              </p>
            </div>
          )}
        </section>
      )}

      <section className="tarjeta">
        <div className="tarjeta-cabecera">
          <h2>Cómo pagas casi siempre</h2>
        </div>
        <p className="ayuda">
          Lo que anotes sin decir cómo lo pagaste va así. Si es en efectivo, sale de tu cartera. Siempre puedes decirlo:
          «45 súper con tarjeta».
        </p>
        <Segmentado
          opciones={[
            { id: 'efectivo', nombre: '💶 Efectivo' },
            { id: 'tarjeta', nombre: '💳 Tarjeta' },
          ]}
          valor={casa.yo.efectivo ? 'efectivo' : 'tarjeta'}
          onCambio={(v) =>
            void cambiarPagoHabitual(token, v === 'efectivo').then(onCambio, onFallo)
          }
          ancho
          etiqueta="Cómo pagas casi siempre"
        />
      </section>

      <section className="tarjeta">
        <form className="formulario" onSubmit={guardarNombre}>
          <label className="campo">
            Tu nombre en casa
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} maxLength={40} />
          </label>
          <div className="botones">
            <span className="derecha">
              <button type="submit" className="boton secundario" disabled={!nombre.trim() || nombre.trim() === casa.yo.nombre}>
                Guardar
              </button>
            </span>
          </div>
        </form>
      </section>
    </>
  )
}
