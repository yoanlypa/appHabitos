"""La vuelta del banco: la página a la que te devuelve Santander tras dar permiso.

No pide token, porque quien llega viene del banco y no de la web: lo que
dice de quién es la vuelta es la clave aleatoria del `state`, que sirve una
vez y caduca en una hora (`servicios/banco.py`). Enseña una página sencilla
con lo que se ve de la cuenta, para comprobarlo en el momento, sin datos
completos: el IBAN va con sus cuatro últimas cifras.
"""
from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.dependencias import get_current_user_id
from app.nucleo import banco as enable
from app.nucleo.db import get_db
from app.servicios import banco

router = APIRouter(prefix="/banco", tags=["banco"])


def _euros(importe) -> str:
    return f"{importe:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def _pagina(titulo: str, cuerpo: str, bien: bool = True) -> HTMLResponse:
    color = "#15803d" if bien else "#c2362c"
    return HTMLResponse(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titulo)}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f7f7f5;color:#1d1d1b;margin:0;padding:24px 16px}}
main{{max-width:560px;margin:0 auto;background:#fff;border:1px solid #e9e8e4;border-radius:14px;padding:20px}}
h1{{font-size:1.3rem;color:{color};margin-top:0}} li{{margin:.3rem 0}} small{{color:#62615c}}
@media (prefers-color-scheme:dark){{body{{background:#0f0f10;color:#ececea}}main{{background:#18181a;border-color:#27272b}}small{{color:#a6a5a0}}}}
</style></head><body><main><h1>{escape(titulo)}</h1>{cuerpo}</main></body></html>""",
        status_code=200 if bien else 400,
    )


@router.get("/vuelta", response_class=HTMLResponse)
async def vuelta(
    state: str = "",
    code: str = "",
    error: str = "",
    error_description: str = "",
    db: Session = Depends(get_db),
):
    if error or not code:
        motivo = error_description or error or "el banco no ha dado permiso"
        return _pagina("No se ha conectado", f"<p>{escape(motivo)}</p><p>Prueba otra vez con /banco en Telegram.</p>", False)
    try:
        r = await banco.completar(db, state, code)
    except banco.ConexionNoValida as exc:
        return _pagina("Este enlace ya no vale", f"<p>{escape(str(exc))}.</p>", False)
    except (enable.BancoNoDisponible, enable.ErrorDeBanco) as exc:
        return _pagina("No se ha conectado", f"<p>{escape(str(exc))}</p>", False)

    dias = r.dias_de_permiso
    cuentas = "".join(
        f"<li>{escape(c.nombre)} <small>{escape(c.tipo)} {escape(c.final_iban)}</small> · "
        f"{c.movimientos} movimientos en {banco.DIAS_DE_MUESTRA} días</li>"
        for c in r.cuentas
    ) or "<li>El banco no ha dejado ver ninguna cuenta.</li>"
    ultimos = "".join(
        f"<li>{m.fecha.strftime('%d/%m') if m.fecha else '¿sin fecha?'} · {escape(m.concepto)} · "
        f"{'−' if m.es_gasto else '+'}{_euros(m.importe)}{' <small>(pendiente)</small>' if m.pendiente else ''}</li>"
        for m in r.ultimos
    )
    cuerpo = (
        f"<p>Conectado con <b>{escape(r.banco)}</b>"
        + (f". El permiso dura <b>{dias} días</b>; cuando caduque, te avisaré para renovarlo." if dias is not None else ".")
        + f"</p><h2>Cuentas</h2><ul>{cuentas}</ul>"
        + (f"<h2>Últimos movimientos</h2><ul>{ultimos}</ul>" if ultimos else "")
        + "<p>Ya puedes cerrar esta página y volver a Telegram.</p>"
    )
    return _pagina("Cuenta conectada ✓", cuerpo)


@router.get("/estructura")
async def estructura(user_id: int = Depends(get_current_user_id), db: Session = Depends(get_db)):
    """Qué campos traen los últimos movimientos (sin conceptos ni importes).

    Para ajustar la lectura a lo que manda cada banco. Pide token: es de
    quien tiene la cuenta conectada.
    """
    try:
        return {"movimientos": await banco.muestra(db, user_id)}
    except (enable.BancoNoDisponible, enable.ErrorDeBanco) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
