"""Envío de mensajes por la Bot API de Telegram (sin dependencias externas)."""

from __future__ import annotations
import html
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import credenciales
import red

red.preparar()          # confiar en los certificados de Windows (redes con antivirus)

ICONO = {"ALTA": "🔴", "MEDIA": "🟡", "BAJA": "🟢"}


def enviar(texto: str, intentos: int = 4) -> bool:
    cred = credenciales.obtener_telegram()
    if not cred:
        print("[telegram] sin configurar → mensaje no enviado:\n" + texto)
        return False
    token, chat_id = cred
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    datos = urllib.parse.urlencode({"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}).encode()
    espera = 2
    for _ in range(intentos):
        try:
            with urllib.request.urlopen(url, data=datos, timeout=20) as r:
                return json.load(r).get("ok", False)
        except urllib.error.HTTPError as e:
            if e.code == 429:                                   # Telegram pide esperar
                espera = json.load(e).get("parameters", {}).get("retry_after", espera)
            elif e.code < 500:
                print(f"[telegram] error {e.code}: {e.read()[:200]!r}")
                return False
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[telegram] red: {e}")
        time.sleep(espera)
        espera *= 2
    return False


def mensaje_notificacion(n: dict, empresa: dict) -> str:
    e = html.escape
    return (f"{ICONO.get(n['prioridad'], '⚪')} <b>{e(n['prioridad'])} · {e(empresa['alias'])}</b> "
            f"(RUC {e(empresa['ruc'])})\n"
            f"{e(n['asunto'])}\n"
            f"Depositada: {e(n['fecha_txt'])} · {e(n['etiqueta'] or 'sin etiqueta')}"
            + ("" if n["buzon"] == "Notificaciones" else f"\n<i>Buzón {e(n['buzon'])}</i>"))


def mensaje_recuperado(empresa: dict) -> str:
    return f"✅ <b>{html.escape(empresa['alias'])}</b> vuelve a revisarse con normalidad."


def mensaje_resumen(fecha: str, filas: list[dict]) -> str:
    """Un solo mensaje con TODAS las empresas revisadas: lo que la contadora mira de un vistazo.
    filas = [{alias, estado, total, nuevas, primera}]. Lo importante (nuevas, errores) va arriba."""
    e = html.escape

    def linea(f):
        a = e(f["alias"])
        if f["estado"] != "OK":
            return f"⚠️ {a} — no se pudo revisar ({e(f['estado'])})"
        if f["primera"]:
            return f"🆕 {a} — historial cargado (1ª vez)"
        if f["nuevas"] > 0:
            return f"🔔 <b>{a} — {f['nuevas']} NUEVA(S)</b> · revisar buzón"
        return f"✅ {a} — sin novedades"

    orden = {"nueva": 0, "error": 1, "primera": 2, "ok": 3}

    def clave(f):
        if f["estado"] != "OK":
            return orden["error"]
        if f["primera"]:
            return orden["primera"]
        return orden["nueva"] if f["nuevas"] > 0 else orden["ok"]

    nuevas_tot = sum(f["nuevas"] for f in filas if f["estado"] == "OK" and not f["primera"])
    fallas = sum(1 for f in filas if f["estado"] != "OK")
    cab = f"📋 <b>Revisión SUNAT</b> · {e(fecha)}"
    if nuevas_tot:
        cab += f"\n🔔 {nuevas_tot} notificación(es) nueva(s) — revisar"
    elif not fallas:
        cab += "\nSin novedades en las " + str(len(filas)) + " empresas"
    cuerpo = "\n".join(linea(f) for f in sorted(filas, key=clave))
    pie = ""
    if fallas:
        # Que un par de empresas no cargue es normal (SUNAT se pone lento o pide captcha).
        # El monitor NO se detiene: sigue con las demás y reintenta en la próxima vuelta.
        pie = (f"\n\n<i>ℹ️ {fallas} empresa(s) no cargaron esta vez. Es normal y el monitor sigue "
               f"funcionando: se reintentan solas en la próxima revisión. Si alguna falla varias "
               f"veces seguidas, conviene revisarla sola desde el panel.</i>")
    return cab + "\n\n" + cuerpo + pie


def mensaje_latido(empresas: list[dict], ultimo: dict) -> str:
    lineas = []
    for emp in empresas:
        est = ultimo.get(emp["ruc"], "sin revisar")
        lineas.append(f"{'✅' if est == 'OK' else '⚠️'} {html.escape(emp['alias'])}: {html.escape(est)}")
    return "🟢 <b>Monitor Buzón SOL activo</b> · resumen diario\n" + "\n".join(lineas)


def mensaje_falla(empresa: dict, estado: str, detalle: str = "") -> str:
    e = html.escape
    return (f"⚠️ <b>No pude revisar {e(empresa['alias'])}</b> (RUC {e(empresa['ruc'])})\n"
            f"Motivo: {e(estado)} {e(detalle[:150])}\nReintento en la próxima vuelta; si es urgente, revisar a mano.")
