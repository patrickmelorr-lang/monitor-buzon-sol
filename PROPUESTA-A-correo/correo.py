"""Propuesta A: lee el correo de alerta de SUNAT por IMAP y avisa por Telegram.

Idea: SUNAT envía un correo al email registrado en la ficha RUC cada vez que deposita
una notificación en el Buzón SOL. Este módulo NO entra al portal de SUNAT (por eso no
choca con el bloqueo al navegador): solo lee un buzón de correo.

Cada correo de SUNAT = una notificación nueva. El anti-duplicado es el Message-ID del
correo (único por mensaje), así que aquí no hace falta restar totales: si hay un correo
que no habíamos visto, es una notificación nueva → se avisa "revisar".

    python correo.py            # lee correos nuevos y avisa por Telegram
    python correo.py --prueba   # muestra qué extraería de los últimos correos, SIN avisar
"""
import argparse
import email
import email.utils
import imaplib
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path

# Propuesta A vive en su propia carpeta pero reutiliza los módulos compartidos de robot/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "robot"))
import config          # noqa: E402
import credenciales    # noqa: E402
import registro        # noqa: E402
import telegram        # noqa: E402

RE_RUC = re.compile(r"\b(10|15|16|17|20)\d{9}\b")          # RUC peruano: 11 dígitos


def _texto(parte) -> str:
    """Decodifica un header o un valor MIME a str limpio."""
    if parte is None:
        return ""
    trozos = []
    for valor, cod in decode_header(str(parte)):
        trozos.append(valor.decode(cod or "utf-8", "replace") if isinstance(valor, bytes) else valor)
    return "".join(trozos)


def _cuerpo(msg) -> str:
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                try:
                    return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
        except Exception:
            pass
    return ""


def _empresa_por_ruc() -> dict[str, dict]:
    return {e["ruc"]: e for e in registro.leer_empresas(solo_activas=False)}


def extraer(msg, empresas: dict[str, dict]) -> dict:
    """De un correo saca empresa (por RUC), asunto y fecha. Tolera lo que no reconoce."""
    asunto = _texto(msg.get("Subject"))
    cuerpo = _cuerpo(msg)
    rucs = [m.group() for m in RE_RUC.finditer(asunto + " " + cuerpo)]
    ruc = next((r for r in rucs if r in empresas), rucs[0] if rucs else "")
    emp = empresas.get(ruc, {"ruc": ruc or "—", "alias": "SUNAT"})
    fechatup = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    return {"msgid": msg.get("Message-ID", "").strip(),
            "ruc": emp["ruc"], "alias": emp["alias"], "asunto": asunto or "(sin asunto)",
            "fecha_txt": fechatup.strftime("%d/%m/%Y %H:%M") if fechatup else "",
            "remitente": _texto(msg.get("From"))}


def _conectar() -> imaplib.IMAP4_SSL:
    cred = credenciales.obtener_correo()
    if not cred:
        raise SystemExit("Falta la credencial de correo. Corre: python credenciales.py correo")
    usuario, clave = cred
    M = imaplib.IMAP4_SSL(config.CORREO_IMAP, config.CORREO_PUERTO)
    M.login(usuario, clave)
    M.select("INBOX")
    return M


def _buscar(M: imaplib.IMAP4_SSL) -> list[bytes]:
    desde = (datetime.now() - timedelta(days=config.CORREO_DIAS_ATRAS)).strftime("%d-%b-%Y")
    ids: list[bytes] = []
    for rem in config.REMITENTES_SUNAT:
        _, datos = M.search(None, "SINCE", desde, "FROM", rem)
        ids += datos[0].split()
    return sorted(set(ids))


def mensaje_alerta(n: dict) -> str:
    import html
    e = html.escape
    return (f"🔔 <b>{e(n['alias'])}</b> (RUC {e(n['ruc'])})\n"
            f"Llegó una notificación a SUNAT. <b>Revisar el Buzón SOL.</b>\n"
            f"Asunto: {e(n['asunto'])}"
            + (f"\nFecha: {e(n['fecha_txt'])}" if n["fecha_txt"] else ""))


def revisar(prueba: bool = False) -> int:
    empresas = _empresa_por_ruc()
    estado = registro.cargar_estado()
    vistos = estado["correos"]
    M = _conectar()
    try:
        ids = _buscar(M)
        print(f"{len(ids)} correos de SUNAT en los últimos {config.CORREO_DIAS_ATRAS} días")
        nuevos = 0
        for i in ids:
            _, datos = M.fetch(i, "(RFC822)")
            msg = email.message_from_bytes(datos[0][1])
            n = extraer(msg, empresas)
            if prueba:
                print(f"  [{n['alias']:10}] {n['fecha_txt']:16} {n['asunto'][:60]}  <{n['remitente'][:40]}>")
                continue
            if not n["msgid"] or n["msgid"] in vistos:
                continue
            if telegram.enviar(mensaje_alerta(n)):
                vistos.append(n["msgid"])
                nuevos += 1
        if not prueba:
            registro.guardar_estado(estado)
            print(f"{nuevos} alertas nuevas enviadas a Telegram")
        return 0
    finally:
        try:
            M.logout()
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prueba", action="store_true")
    sys.exit(revisar(prueba=ap.parse_args().prueba))
