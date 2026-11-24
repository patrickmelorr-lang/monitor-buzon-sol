"""Monitor del Buzón SOL SUNAT → Telegram + Excel.

    python robot.py                      # revisa las empresas con MONITOREAR = SÍ
    python robot.py --ruc 20XXXXXXXXX    # solo una empresa
    python robot.py --explorar --ruc ... # navegador visible + capturas/HTML en logs/ (para ajustar)
    python robot.py --silencioso         # registra todo sin mandar Telegram
    python robot.py --prueba-telegram    # manda un mensaje de prueba

La primera vez que se revisa un RUC, todo lo que hay en su buzón se registra SIN alertar
(carga inicial). Desde la segunda vuelta, solo lo nuevo genera mensaje.
"""

from __future__ import annotations
import argparse
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

import config
import credenciales
import registro
import reglas
import sunat
import telegram

AVISAR_FALLA = {"LOGIN_FALLIDO", "CAPTCHA", "CAMBIO_PAGINA", "ERROR"}   # SESION_ACTIVA/TIMEOUT son pasajeros


def lanzar(pw, visible: bool):
    try:
        return pw.chromium.launch(channel="chrome", headless=not visible)   # Chrome instalado
    except Exception:
        return pw.chromium.launch(headless=not visible)                     # Chromium de Playwright


def procesar(empresa: dict, res: sunat.Resultado, estado: dict, silencioso: bool, filas: list) -> int:
    """Registra/alerta lo nuevo de una empresa. Devuelve cuántas notificaciones nuevas hubo."""
    primera_vez = empresa["ruc"] not in estado["rucs"]
    callar = silencioso or primera_vez
    nuevas = 0
    for it in reversed(res.items):                       # SUNAT lista lo más nuevo arriba → avisar en orden
        nid = registro.hacer_id(empresa["ruc"], it["fecha_txt"], it["asunto"])
        if nid in estado["ids"]:
            continue
        tipo, num = reglas.tipo_y_numero(it["asunto"])
        n = {**it, "id": nid, "tipo": tipo, "numero": num,
             "prioridad": reglas.prioridad(it["etiqueta"], it["asunto"]), "silenciosa": callar}
        if callar:
            alertada = False
        else:
            print(f"   enviando Telegram: {n['asunto'][:55]}...", flush=True)
            alertada = telegram.enviar(telegram.mensaje_notificacion(n, empresa))
            if not alertada:
                continue                                 # no se marca como vista: se reintenta luego
        estado["ids"].add(nid)
        filas.append(registro.fila_notificacion(n, empresa, alertada))
        nuevas += 1
    estado["rucs"].add(empresa["ruc"])
    registro.guardar_estado(estado)                       # tras cada empresa: a prueba de cortes
    if callar and nuevas:
        print(f"   carga inicial silenciosa: {nuevas} registradas sin alerta")
    return nuevas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ruc")
    ap.add_argument("--rucs", help="varias empresas separadas por coma (si se omite: todas las activas)")
    ap.add_argument("--explorar", action="store_true")
    ap.add_argument("--visible", action="store_true")
    ap.add_argument("--silencioso", action="store_true")
    ap.add_argument("--prueba-telegram", action="store_true")
    ap.add_argument("--prueba-ultima", action="store_true",
                    help="manda la notificación más reciente registrada de cada empresa")
    ap.add_argument("--sin-resumen", action="store_true",
                    help="no mandar el resumen de todas las empresas al final de la vuelta")
    ap.add_argument("--log", action="store_true", help="escribir la salida en logs/robot.log")
    a = ap.parse_args()
    # Asegura que "→", "✅", etc. no revienten cuando la salida va a un pipe cp1252 (Windows).
    for flujo in (sys.stdout, sys.stderr):
        try:
            # line_buffering: que el panel vea el avance en vivo y no todo junto al final.
            flujo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass
    if a.log or sys.stdout is None:
        redirigir_salida()

    if a.prueba_ultima:
        return prueba_ultima(a.ruc)
    if a.prueba_telegram:
        ok = telegram.enviar("✅ Monitor Buzón SOL conectado. Aquí llegarán las notificaciones SUNAT.")
        print("Telegram:", "enviado" if ok else "FALLÓ")
        return 0 if ok else 1

    # Selección de empresas: --rucs 2061...,2060...  (el panel manda las marcadas con ✔)
    seleccion = {r.strip() for r in (a.rucs or "").split(",") if r.strip()}
    if a.ruc:
        seleccion.add(a.ruc)
    a.parcial = bool(seleccion)                      # ¿es un subconjunto y no el barrido completo?
    empresas = registro.leer_empresas(solo_activas=not seleccion)
    if seleccion:
        empresas = [e for e in empresas if e["ruc"] in seleccion]
    if not empresas:
        print("No hay empresas para revisar (revisa MONITOREAR = SÍ o el RUC).")
        return 1

    if not _tomar_lock():
        print("Ya hay una revisión en curso (botón o tarea). No arranco otra.")
        return 0
    estado = registro.cargar_estado()
    filas_notif, filas_log, revisiones, hubo_falla = [], [], {}, False
    try:
        hubo_falla = revisar_todas(a, empresas, estado, filas_notif, filas_log, revisiones)
    finally:
        # Aunque se cierre la ventana o falle una empresa, lo ya leído queda en el Excel
        # (vistos.json se guarda tras cada empresa; sin esto el Excel quedaba atrás).
        registro.guardar_corrida(filas_notif, filas_log, revisiones)
        _soltar_lock()
    return 1 if hubo_falla else 0


def prueba_ultima(ruc: str | None) -> int:
    """Manda a Telegram la notificación más reciente registrada de cada empresa (sin entrar a SUNAT)."""
    empresas = registro.leer_empresas(solo_activas=ruc is None)
    if ruc:
        empresas = [e for e in empresas if e["ruc"] == ruc]
    ultimas = registro.ultima_por_ruc()
    enviados = 0
    for emp in empresas:
        n = ultimas.get(emp["ruc"])
        if not n:
            print(f"   {emp['alias']}: aún sin notificaciones registradas (falta su 1ª revisión)")
            continue
        n["prioridad"] = reglas.prioridad(n["etiqueta"], n["asunto"])
        ok = telegram.enviar("🧪 <b>PRUEBA</b> · última notificación registrada\n"
                             + telegram.mensaje_notificacion(n, emp))
        print(f"   {emp['alias']}: {n['fecha_txt']} → {'enviado' if ok else 'FALLÓ'}")
        enviados += ok
    return 0 if enviados else 1


def revisar_todas(a, empresas, estado, filas_notif, filas_log, revisiones) -> bool:
    hubo_falla = False
    resumen = []                                          # una línea por empresa, para el Telegram de cierre
    with sync_playwright() as pw:
        navegador = lanzar(pw, a.visible or a.explorar)
        for i, emp in enumerate(empresas):
            if i:
                print(f"   (pausa de {config.PAUSA_ENTRE_EMPRESAS_S}s para no saturar a SUNAT)",
                      flush=True)
                time.sleep(config.PAUSA_ENTRE_EMPRESAS_S)
            print(f"-> [{i + 1}/{len(empresas)}] {emp['alias']} ({emp['ruc']})", flush=True)
            primera = emp["ruc"] not in estado["rucs"]    # ¿es su 1ª revisión? (antes de procesar)
            cred = credenciales.obtener_sol(emp["ruc"])
            if not cred:
                res = sunat.Resultado("LOGIN_FALLIDO", "Sin credencial en el Administrador de Windows")
            else:
                ctx = navegador.new_context(locale="es-PE", viewport={"width": 1400, "height": 900})
                res = sunat.revisar(ctx, emp["ruc"], *cred, explorar=a.explorar)
                ctx.close()
            nuevas = procesar(emp, res, estado, a.silencioso, filas_notif) if res.estado == "OK" else 0
            resumen.append({"alias": emp["alias"], "estado": res.estado,
                            "total": len(res.items), "nuevas": nuevas, "primera": primera})
            print(f"   {res.estado} · {len(res.items)} en lista · {nuevas} nuevas · "
                  f"{res.segundos}s {res.detalle}", flush=True)
            ahora = datetime.now()
            filas_log.append([ahora, emp["ruc"], emp["alias"], res.estado, len(res.items), nuevas,
                              res.segundos, res.detalle])
            revisiones[emp["ruc"]] = (ahora, res.estado if res.estado != "OK" else f"OK · {nuevas} nuevas")
            # Con revisiones cada 30 min, una falla que persiste avisaría 48 veces al día:
            # se avisa solo cuando el estado CAMBIA, y otra vez cuando se recupera.
            previo = estado["ultimo"].get(emp["ruc"], "OK")
            if res.estado != "OK":
                hubo_falla = True
                if res.estado in AVISAR_FALLA and res.estado != previo and not a.silencioso:
                    telegram.enviar(telegram.mensaje_falla(emp, res.estado, res.detalle))
            elif previo in AVISAR_FALLA and not a.silencioso:
                telegram.enviar(telegram.mensaje_recuperado(emp))
            estado["ultimo"][emp["ruc"]] = res.estado
            registro.guardar_estado(estado)
        navegador.close()

    # Resumen de la vuelta: TODAS las empresas en un solo mensaje. Es lo que la contadora
    # mira en Telegram para saber que el robot trabajó y qué empresa tiene algo que revisar.
    if resumen and not a.silencioso and not a.sin_resumen:
        telegram.enviar(telegram.mensaje_resumen(f"{datetime.now():%d/%m %H:%M}", resumen))

    # Latido diario: si un día no llega este resumen, el robot está caído (PC apagada, error...).
    hoy = datetime.now().date().isoformat()
    if (not a.silencioso and not getattr(a, "parcial", False) and estado["latido"] != hoy
            and datetime.now().hour >= config.HORA_LATIDO):
        if telegram.enviar(telegram.mensaje_latido(empresas, estado["ultimo"])):
            estado["latido"] = hoy
            registro.guardar_estado(estado)
    return hubo_falla


def _tomar_lock() -> bool:
    """Candado para que el botón del panel y la tarea de Windows nunca corran a la vez.
    Un lock de más de 15 min se considera abandonado (la corrida anterior murió) y se pisa:
    un barrido completo de 11 empresas tarda ~6 min, así que 15 da margen de sobra."""
    lock = config.ESTADO_VISTOS.parent / "robot.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        import time as _t
        if _t.time() - lock.stat().st_mtime < 15 * 60:
            return False
    lock.write_text(str(datetime.now()), encoding="utf-8")
    return True


def _soltar_lock() -> None:
    (config.ESTADO_VISTOS.parent / "robot.lock").unlink(missing_ok=True)


def redirigir_salida() -> None:
    """Bajo el Programador de tareas (pythonw) no hay consola: todo va a logs/robot.log."""
    config.DIR_LOGS.mkdir(parents=True, exist_ok=True)
    log = config.DIR_LOGS / "robot.log"
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(log.with_suffix(".log.1"))            # rotación simple: guarda 1 anterior
    sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
    print(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====")


if __name__ == "__main__":
    sys.exit(main())
