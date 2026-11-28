"""Login SOL -> lista del Buzón de Notificaciones -> Salir.

Dos reglas de oro:

1. Solo se LEE la lista. Nunca se hace clic en una notificación, para que sigan
   figurando como "no leídas" en SUNAT.
2. NUNCA se afirma "no hay notificaciones" sin que SUNAT lo confirme. La página
   muestra un contador ("1-16 de 16") que es la verdad publicada por el propio
   SUNAT: si dice 16 y extrajimos 14, la lectura está incompleta y lo sabemos
   con certeza. Si el contador no aparece, el resultado es SIN_CONFIRMAR, nunca
   "vacío". Un falso "sin novedades" es el peor error posible en este sistema.
"""
from __future__ import annotations

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
# El contador del buzón: "1-16 de 16", "1 - 25 de 99". Es nuestra verificación.
RE_CONTADOR = re.compile(r"(\d+)\s*-\s*(\d+)\s+de\s+(\d+)", re.I)
# Señales de que el buzón cargó aunque esté vacío.
MARCAS_BUZON = ("buscar por asunto", "buzón notificaciones", "buzon notificaciones",
                "buzón mensajes", "mis carpetas")
RE_VACIO = re.compile(r"no\s+(se\s+encontraron|tiene|hay)\s+.{0,30}(notificaci|mensaje|registro)", re.I)


@dataclass
class Resultado:
    # OK | VACIO | SIN_CONFIRMAR | LOGIN_FALLIDO | CAPTCHA | SESION_ACTIVA
    # | TIMEOUT | CAMBIO_PAGINA | VENTANA_CERRADA | ERROR
    estado: str = "OK"
    detalle: str = ""
    items: list = field(default_factory=list)
    segundos: float = 0.0
    esperadas: int | None = None      # cuántas dice SUNAT que hay en esta página
    total_sunat: int | None = None    # total del buzón según el contador
    intentos: int = 1

    @property
    def confiable(self) -> bool:
        """True solo si SUNAT confirmó el resultado. Lo que decide si se puede
        decir 'sin novedades' sin mentir."""
        return self.estado in ("OK", "VACIO")


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
        except Exception as e:
            print(f"[explorar] no pude guardar {paso}: {e}", flush=True)


def _texto_frames(page: Page) -> str:
    partes = []
    for fr in page.frames:
        try:
            partes.append(fr.locator("body").inner_text(timeout=1500))
        except Exception:
            pass
    return "\n".join(partes)


def _leer_contador(texto: str) -> tuple[int, int, int] | None:
    """Devuelve (desde, hasta, total) del contador del buzón, o None si no está."""
    mejor = None
    for m in RE_CONTADOR.finditer(texto):
        desde, hasta, total = (int(g) for g in m.groups())
        # desde puede ser 0 cuando el buzón está vacío ("0-0 de 0").
        if desde >= 0 and hasta >= desde and total >= hasta:
            mejor = (desde, hasta, total)
            break
    return mejor


def _visible(page: Page, selector: str) -> bool:
    return any(fr.locator(selector).first.is_visible() for fr in page.frames
               if fr.locator(selector).count())


def _login(page: Page, ruc: str, usuario: str, clave: str, dbg: _Depurador,
           techo: float) -> Resultado | None:
    # Se entra por URL_LOGIN (lleva "state"): si se entra por MenuInternet.htm pelado, SUNAT
    # devuelve a api-seguridad con state vacío y se queda en "Bienvenidos a SUNAT" sin avanzar.
    page.goto(config.URL_LOGIN, wait_until="domcontentloaded")
    page.wait_for_selector("#txtRuc, #btnPorRuc", timeout=techo * 1000)
    if page.locator("#btnPorRuc").is_visible():
        page.click("#btnPorRuc")
    page.fill("#txtRuc", ruc)
    page.fill("#txtUsuario", usuario.upper())
    page.fill("#txtContrasena", clave)
    dbg.foto(page, "01_login", html=False)                       # sin HTML: hay una clave escrita
    if _visible(page, "#txtCaptcha"):
        return Resultado("CAPTCHA", "SUNAT pidió captcha antes de ingresar")
    page.click("#btnAceptar")

    limite = time.time() + techo
    rescatado = False
    while time.time() < limite:
        page.wait_for_timeout(700)
        if "e-menu.sunat.gob.pe" in page.url:
            return None
        if not rescatado and "api-seguridad" in page.url and "code=" in page.url:
            rescatado = True
            print("   (pantalla de bienvenida: entrando al buzón directo)", flush=True)
            page.goto(config.URL_BUZON, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if "e-menu.sunat.gob.pe" in page.url:
                return None
            continue
        if _visible(page, "#btnWithOutCode"):
            page.click("#btnWithOutCode")
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


def _leer_lista(page: Page, dbg: _Depurador, techo: float) -> Resultado:
    """Lee la lista y la VERIFICA contra el contador de SUNAT.

    No concluye por reloj: espera a que (a) aparezca el contador y (b) el número de
    tarjetas deje de cambiar. Solo entonces compara. Si no logra cuadrar, devuelve
    SIN_CONFIRMAR: jamás inventa un 'vacío'.
    """
    page.goto(config.URL_BUZON, wait_until="domcontentloaded")
    print("   leyendo buzon...", flush=True)
    inicio = time.time()
    limite = inicio + techo
    anterior = -1
    estables = 0
    items: list = []
    contador = None
    shell = False

    while time.time() < limite:
        page.wait_for_timeout(1200)
        texto = _texto_frames(page)
        shell = shell or any(m in texto.lower() for m in MARCAS_BUZON)
        contador = _leer_contador(texto) or contador

        crudos = []
        for fr in page.frames:
            try:
                crudos += fr.evaluate(JS_EXTRAER)
            except Exception:
                pass                                             # frame recargándose: se reintenta
        vistos, items = set(), []
        for c in crudos:
            it = parsear_item(c["texto"])
            if it and (it["fecha_txt"], it["asunto"]) not in vistos:
                vistos.add((it["fecha_txt"], it["asunto"]))
                items.append(it)

        estables = estables + 1 if len(items) == anterior else 0
        anterior = len(items)

        if contador:
            desde, hasta, total = contador
            esperadas = hasta - desde + 1 if total else 0
            if total == 0:
                dbg.foto(page, "03_buzon")
                return Resultado("VACIO", "SUNAT confirma que el buzón está vacío",
                                 esperadas=0, total_sunat=0)
            if len(items) >= esperadas and estables >= 1:
                dbg.foto(page, "03_buzon")
                return Resultado(items=items, esperadas=esperadas, total_sunat=total,
                                 detalle=f"verificado contra el contador ({esperadas} de {total})")
        elif shell and RE_VACIO.search(texto) and estables >= 2:
            dbg.foto(page, "03_buzon")
            return Resultado("VACIO", "SUNAT informa que no hay notificaciones",
                             esperadas=0, total_sunat=0)

    # Se agotó la paciencia sin poder verificar.
    dbg.foto(page, "03_buzon_sin_confirmar")
    if contador:
        desde, hasta, total = contador
        esperadas = hasta - desde + 1
        return Resultado("SIN_CONFIRMAR",
                         f"SUNAT indica {esperadas} notificaciones en pantalla y solo leí "
                         f"{len(items)}: lectura incompleta",
                         items=items, esperadas=esperadas, total_sunat=total)
    if not shell:
        return Resultado("CAMBIO_PAGINA", "No llegué a la pantalla del buzón")
    return Resultado("SIN_CONFIRMAR",
                     f"El buzón cargó pero no encontré el contador para verificar "
                     f"(leí {len(items)}). No afirmo que esté vacío.", items=items)


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


def revisar(contexto: BrowserContext, ruc: str, usuario: str, clave: str,
            explorar: bool = False, paciencia: float = 1.0) -> Resultado:
    """Una pasada por el buzón de un RUC.

    paciencia multiplica los tiempos de espera: el robot la sube en cada reintento,
    porque la causa más común de una lectura incompleta es que la página tardó más
    de lo previsto (SUNAT lento, PC cargada).
    """
    t0 = time.time()
    techo = config.TIMEOUT_MS / 1000 * paciencia
    dbg = _Depurador(ruc, explorar)
    page = contexto.new_page()
    page.set_default_timeout(int(techo * 1000))
    logueado = False
    try:
        print("   entrando a SUNAT...", flush=True)
        fallo = _login(page, ruc, usuario, clave, dbg, techo)
        if fallo:
            res = fallo
        else:
            logueado = True
            res = _leer_lista(page, dbg, techo)
    except PWTimeout as e:
        dbg.foto(page, "99_timeout", html=False)
        res = Resultado("TIMEOUT", str(e).splitlines()[0][:150])
    except Exception as e:
        nombre, txt = type(e).__name__, str(e)
        if "TargetClosed" in nombre or "has been closed" in txt:
            res = Resultado("VENTANA_CERRADA", "Se cerró la ventana de Chrome durante la revisión")
        else:
            dbg.foto(page, "99_error", html=False)
            res = Resultado("ERROR", f"{nombre}: {txt[:150]}")
    finally:
        try:
            if logueado:
                _salir(page)                                     # liberar la sesión para la persona
            page.close()
        except Exception:
            pass
    res.segundos = round(time.time() - t0, 1)
    return res
