"""Claves SOL y token de Telegram en el Administrador de Credenciales de Windows.

Uso (lo ejecuta una persona, una sola vez):
    python credenciales.py migrar      # copia usuario/clave de CLAVE SOL.xlsx al almacén de Windows
    python credenciales.py telegram    # pide el token del bot (oculto) y el chat_id
    python credenciales.py verificar   # dice qué RUC tienen credencial, SIN mostrar claves
"""
import getpass
import os
import sys

import keyring
import openpyxl

import config


def _secreto(servicio: str, clave: str, env: str) -> str | None:
    """Primero el Administrador de Windows; si no, una variable de entorno (para GitHub Actions)."""
    try:
        v = keyring.get_password(servicio, clave)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(env)


def obtener_sol(ruc: str) -> tuple[str, str] | None:
    """Devuelve (usuario, clave) o None si ese RUC no fue migrado."""
    secreto = keyring.get_password(config.KR_SERVICIO_SOL, ruc)
    if not secreto:
        return None
    usuario, _, clave = secreto.partition("|")
    return usuario, clave


def obtener_telegram() -> tuple[str, str] | None:
    token = _secreto(config.KR_SERVICIO_TG, "token", "TG_TOKEN")
    chat = _secreto(config.KR_SERVICIO_TG, "chat_id", "TG_CHAT_ID")
    return (token, chat) if token and chat else None


def obtener_correo() -> tuple[str, str] | None:
    """(email, app_password) del buzón que recibe las alertas de SUNAT."""
    email_dir = _secreto(config.KR_SERVICIO_CORREO, "email", "CORREO_EMAIL")
    clave = _secreto(config.KR_SERVICIO_CORREO, "password", "CORREO_PASSWORD")
    return (email_dir, clave) if email_dir and clave else None


def migrar() -> None:
    ws = openpyxl.load_workbook(config.EXCEL_CLAVES, data_only=True).active
    n = 0
    for fila in ws.iter_rows(min_row=5, values_only=True):
        razon, ruc, usuario, clave = fila[2], fila[3], fila[4], fila[5]
        if not (razon and ruc and usuario and clave):
            continue
        keyring.set_password(config.KR_SERVICIO_SOL, str(ruc).strip(),
                             f"{str(usuario).strip()}|{str(clave).strip()}")
        n += 1
        print(f"  ✔ {ruc}  {razon}")
    print(f"\n{n} credenciales guardadas en el Administrador de Credenciales de Windows "
          f"(servicio '{config.KR_SERVICIO_SOL}').")
    print("Siguiente paso: verifica con 'python credenciales.py verificar' y luego BORRA la "
          "columna de claves de CLAVE SOL.xlsx (o guarda ese archivo cifrado).")


def telegram() -> None:
    token = getpass.getpass("Token del bot (de @BotFather, no se mostrará): ").strip()
    chat = input("chat_id del grupo (ej. -1001234567890): ").strip()
    keyring.set_password(config.KR_SERVICIO_TG, "token", token)
    keyring.set_password(config.KR_SERVICIO_TG, "chat_id", chat)
    print("Guardado. Prueba con: python robot.py --prueba-telegram")


def correo() -> None:
    email_dir = input("Email que recibe las alertas de SUNAT (ej. notificaciones@tuempresa.com): ").strip()
    print("App password: en Gmail es una clave de 16 letras que se crea en "
          "Cuenta de Google → Seguridad → Contraseñas de aplicaciones (NO tu clave normal).")
    clave = getpass.getpass("App password (no se mostrará): ").strip().replace(" ", "")
    keyring.set_password(config.KR_SERVICIO_CORREO, "email", email_dir)
    keyring.set_password(config.KR_SERVICIO_CORREO, "password", clave)
    print("Guardado. Prueba con: python correo.py --prueba")


def verificar() -> None:
    import registro
    for e in registro.leer_empresas(solo_activas=False):
        ok = "✔" if obtener_sol(e["ruc"]) else "✘ falta"
        print(f"  {ok:8} {e['ruc']}  {e['alias']:10} monitorear={e['monitorear']}")
    print("Telegram:", "✔ configurado" if obtener_telegram() else "✘ falta")
    print("Correo:  ", "✔ configurado" if obtener_correo() else "✘ falta")


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    {"migrar": migrar, "telegram": telegram, "correo": correo, "verificar": verificar}.get(
        accion, lambda: print(__doc__))()
