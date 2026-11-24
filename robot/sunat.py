"""Login SOL → lista del Buzón de Notificaciones → Salir.

Regla de oro: solo se LEE la lista. Nunca se hace clic en una notificación.
"""
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

import config

# Extrae las tarjetas de la lista en cualquier frame. Primero el selector conocido
# (.list-group-item); si SUNAT cambia el HTML, cae a "el nodo más chico que tenga
# exactamente un 'ASUNTO:' y una fecha".
JS_EXTRAER = r"""() => {
  const reFecha = /\d{2}\/\d{2}\/\d{4}\s+\d{2}:\d{2}(:\d{2})?/;
  const unAsunto = t => (t.match(/ASUNTO:/gi) || []).length === 1;
  let nodos = [...document.querySelectorAll('.list-group-item')]
      .filter(n => reFecha.test(n.innerText || '') && unAsunto(n.innerText || ''));
  if (!nodos.length) {
    const cand = [...document.querySelectorAll('li, tr, div, a')]
        .filter(n => reFecha.test(n.innerText || '') && unAsunto(n.innerText || ''));
    nodos = cand.filter(n => !cand.some(o => o !== n && n.contains(o)));
  }
  return nodos.map(n => ({texto: n.innerText, clase: String(n.className || '')}));
}"""

RE_FECHA = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})(:\d{2})?")
RE_SESION_ACTIVA = re.compile(r"sesi[oó]n\s+(activa|abierta)|ya\s+se\s+encuentra\s+conectad", re.I)


@dataclass
class Resultado:
    estado: str = "OK"            # OK | LOGIN_FALLIDO | CAPTCHA | SESION_ACTIVA | TIMEOUT | CAMBIO_PAGINA | ERROR
    detalle: str = ""
    items: list = field(default_factory=list)   # [{"asunto", "fecha_txt", "etiqueta", "buzon"}]
    segundos: float = 0.0


def parsear_item(texto: str, buzon: str = "Notificaciones") -> dict | None:
    plano = " ".join(l.strip() for l in texto.splitlines() if l.strip())
    m = RE_FECHA.search(plano)
    if not m:
        return None
    asunto = re.sub(r"^\s*ASUNTO:\s*", "", plano[: m.start()], flags=re.I).strip()
    etiqueta = plano[m.end():].strip(" -·|")
    fecha_txt = f"{m.group(1)} {m.group(2)}{m.group(3) or ':00'}"
    return {"asunto": asunto, "fecha_txt": fecha_txt, "etiqueta": etiqueta.upper(), "buzon": buzon}


class _Depurador:
    """En modo --explorar guarda captura + HTML de cada frame para ajustar selectores."""

    def __init__(self, ruc: str, activo: bool):
        self.activo = activo
        self.dir = config.DIR_LOGS / f"{ruc}_{datetime.now():%Y%m%d_%H%M%S}"

    def foto(self, page: Page, paso: str, html: bool = True) -> None:
        if not self.activo:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(self.dir / f"{paso}.png"), full_page=True)
            if html:
                for i, fr in enumerate(page.frames):
                    Path(self.dir / f"{paso}_frame{i}.html").write_text(
                        f"<!-- {fr.url} -->\n" + fr.content(), encoding="utf-8")
        except Exception as e:                                   # depurar nunca debe tumbar el robot
            print(f"[explorar] no pude guardar {paso}: {e}")


def _visible(page: Page, selector: str) -> bool:
    return any(fr.locator(selector).first.is_visible() for fr in page.frames
               if fr.locator(selector).count())


def _login(page: Page, ruc: str, usuario: str, clave: str, dbg: _Depurador) -> Resultado | None:
    # Se entra por URL_LOGIN (lleva "state"): si se entra por MenuInternet.htm pelado, SUNAT
    # devuelve a api-seguridad con state vacío y se queda en "Bienvenidos a SUNAT" sin avanzar.
    page.goto(config.URL_LOGIN, wait_until="domcontentloaded")
    page.wait_for_selector("#txtRuc, #btnPorRuc", timeout=config.TIMEOUT_MS)
    if page.locator("#btnPorRuc").is_visible():
        page.click("#btnPorRuc")
    page.fill("#txtRuc", ruc)
    page.fill("#txtUsuario", usuario.upper())
    page.fill("#txtContrasena", clave)
    dbg.foto(page, "01_login", html=False)                       # sin HTML: hay una clave escrita
    if _visible(page, "#txtCaptcha"):
        return Resultado("CAPTCHA", "SUNAT pidió captcha antes de ingresar")
    page.click("#btnAceptar")

    # Esperar a: menú SOL, error, captcha, o pantalla de "código de verificación".
    limite = time.time() + config.TIMEOUT_MS / 1000
    rescatado = False
    while time.time() < limite:
        page.wait_for_timeout(700)
        if "e-menu.sunat.gob.pe" in page.url:
            return None                                          # login correcto
        # Rescate: quedó en api-seguridad/?code=... ("Bienvenidos a SUNAT") sin seguir al menú.
        # La sesión ya está creada, así que entramos al buzón por la puerta directa. Una sola vez.
        if not rescatado and "api-seguridad" in page.url and "code=" in page.url:
            rescatado = True
            print("   (pantalla de bienvenida: entrando al buzón directo)", flush=True)
            page.goto(config.URL_BUZON, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if "e-menu.sunat.gob.pe" in page.url:
                return None
            continue
        if _visible(page, "#btnWithOutCode"):
            page.click("#btnWithOutCode")                        # continuar sin código
            continue
        for sel in ("#divMensajeError", "#spanMensajeError"):
            if _visible(page, sel):
                return Resultado("LOGIN_FALLIDO", page.locator(sel).first.inner_text()[:150])
        if _visible(page, "#txtCaptcha"):
            return Resultado("CAPTCHA", "SUNAT pidió captcha")
        if RE_SESION_ACTIVA.search(page.locator("body").inner_text()):
            return Resultado("SESION_ACTIVA", "Hay otra sesión abierta en este RUC")
    dbg.foto(page, "02_login_sin_respuesta")
    return Resultado("TIMEOUT", f"Login sin respuesta; URL final: {page.url[:90]}")


# Textos que solo aparecen si el buzón realmente cargó. Sirven para saber si "0 notificaciones"
# significa buzón vacío (normal) o que no encontramos la lista (hay que revisar selectores).
MARCAS_BUZON = ("buscar por asunto", "buzón notificaciones", "buzon notificaciones",
                "buzón mensajes", "mis carpetas")


def _buzon_cargado(page: Page) -> bool:
    for fr in page.frames:
        try:
            texto = fr.locator("body").inner_text(timeout=1500).lower()
        except Exception:
            continue
        if any(m in texto for m in MARCAS_BUZON):
            return True
    return False


def _leer_lista(page: Page, dbg: _Depurador) -> tuple[list[dict], bool]:
    """Devuelve (notificaciones, buzón_cargó). Si cargó y la lista está vacía, es buzón vacío."""
    page.goto(config.URL_BUZON, wait_until="domcontentloaded")
    print("   leyendo buzón...", flush=True)
    inicio = time.time()
    limite = inicio + config.TIMEOUT_MS / 1000
    crudos, shell = [], False
    while time.time() < limite and not crudos:
        page.wait_for_timeout(1500)
        shell = shell or _buzon_cargado(page)
        for fr in page.frames:
            try:
                crudos += fr.evaluate(JS_EXTRAER)
            except Exception:
                pass                                             # frame que se recargó: se reintenta
        if shell and not crudos and time.time() - inicio > 12:
            break                                                # cargó y sigue vacío: no esperar más
    dbg.foto(page, "03_buzon")
    vistos, items = set(), []
    for c in crudos:
        it = parsear_item(c["texto"])
        if it and (it["fecha_txt"], it["asunto"]) not in vistos:
            vistos.add((it["fecha_txt"], it["asunto"]))
            items.append(it)
    return items, shell


def _salir(page: Page) -> None:
    for fr in page.frames:
        for sel in ("#btnSalir", "text=Salir"):
            try:
                if fr.locator(sel).count() and fr.locator(sel).first.is_visible():
                    fr.locator(sel).first.click(timeout=5000)
                    page.wait_for_timeout(1500)
                    return
            except Exception:
                pass


def revisar(contexto: BrowserContext, ruc: str, usuario: str, clave: str, explorar: bool = False) -> Resultado:
    t0 = time.time()
    dbg = _Depurador(ruc, explorar)
    page = contexto.new_page()
    page.set_default_timeout(config.TIMEOUT_MS)
    logueado = False
    try:
        print("   entrando a SUNAT...", flush=True)
        fallo = _login(page, ruc, usuario, clave, dbg)
        if fallo:
            res = fallo
        else:
            logueado = True
            items, shell = _leer_lista(page, dbg)
            if items:
                res = Resultado(items=items)
            elif shell:
                print("   buzón sin notificaciones", flush=True)
                res = Resultado(items=[])                        # buzón vacío: es un OK, no un error
            else:
                res = Resultado("CAMBIO_PAGINA",
                                "No encontré la lista del buzón (correr con --explorar)")
    except PWTimeout as e:
        dbg.foto(page, "99_timeout", html=False)
        res = Resultado("TIMEOUT", str(e).splitlines()[0][:150])
    except Exception as e:
        nombre, txt = type(e).__name__, str(e)
        if "TargetClosed" in nombre or "has been closed" in txt:
            # Alguien cerró la ventana de Chrome (o se canceló). No es una falla de SUNAT.
            res = Resultado("VENTANA_CERRADA", "Se cerró la ventana de Chrome durante la revisión")
        else:
            dbg.foto(page, "99_error", html=False)
            res = Resultado("ERROR", f"{nombre}: {txt[:150]}")
    finally:
        try:
            if logueado:
                _salir(page)                                     # liberar la sesión para la contadora
            page.close()
        except Exception:
            pass                                                 # la ventana ya no existe
    res.segundos = round(time.time() - t0, 1)
    return res
