"""Cofre de credenciales: las lleva cifradas dentro del portable.

Las Claves SOL viajan a la PC de la contadora dentro del paquete, pero NUNCA en texto
plano: van en un archivo cifrado que solo se abre con una contraseña maestra que tú le
das por otro canal (teléfono, en persona). Al abrirlo en su PC, las claves pasan a SU
Administrador de Credenciales de Windows y el archivo cifrado puede borrarse.

    python cofre.py exportar     # en TU PC: keyring -> credenciales.cifradas
    python cofre.py importar     # en la PC de la contadora: cifradas -> su keyring
"""
import base64
import getpass
import json
import sys
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import config
import credenciales
import registro

ARCHIVO = config.ROBOT / "credenciales.cifradas"
VUELTAS = 600_000                      # iteraciones PBKDF2: encarece el probar contraseñas a la fuerza


def _llave(password: str, sal: bytes) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=VUELTAS)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))


def _pedir_password(confirmar: bool = False) -> str:
    p = getpass.getpass("Contraseña maestra del cofre (no se mostrará): ").strip()
    if len(p) < 8:
        sys.exit("La contraseña debe tener al menos 8 caracteres.")
    if confirmar and p != getpass.getpass("Repite la contraseña: ").strip():
        sys.exit("No coinciden.")
    return p


def exportar() -> None:
    datos = {"sol": {}, "telegram": {}}
    for e in registro.leer_empresas(solo_activas=False):
        par = credenciales.obtener_sol(e["ruc"])
        if par:
            datos["sol"][e["ruc"]] = {"usuario": par[0], "clave": par[1]}
    tg = credenciales.obtener_telegram()
    if tg:
        datos["telegram"] = {"token": tg[0], "chat_id": tg[1]}
    if not datos["sol"]:
        sys.exit("No hay credenciales en el Administrador de Windows. Corre antes: "
                 "python credenciales.py migrar")

    print(f"Se cifrarán {len(datos['sol'])} Claves SOL"
          f"{' + Telegram' if datos['telegram'] else ''}.")
    password = _pedir_password(confirmar=True)
    sal = __import__("os").urandom(16)
    blob = _llave(password, sal).encrypt(json.dumps(datos).encode())
    ARCHIVO.write_bytes(sal + blob)                 # sal (16 bytes) + contenido cifrado
    print(f"\nListo: {ARCHIVO.name} ({ARCHIVO.stat().st_size} bytes)")
    print("Va DENTRO del portable. La contraseña maestra se la das a la contadora por")
    print("otro medio (teléfono o en persona), NUNCA en el mismo correo o USB.")


def importar(ruta: Path | None = None) -> None:
    arch = ruta or ARCHIVO
    if not arch.exists():
        sys.exit(f"No encuentro {arch.name} junto a estos archivos.")
    crudo = arch.read_bytes()
    password = _pedir_password()
    try:
        datos = json.loads(_llave(password, crudo[:16]).decrypt(crudo[16:]))
    except (InvalidToken, ValueError):
        sys.exit("Contraseña incorrecta o archivo dañado.")

    for ruc, d in datos.get("sol", {}).items():
        keyring.set_password(config.KR_SERVICIO_SOL, ruc, f"{d['usuario']}|{d['clave']}")
    tg = datos.get("telegram") or {}
    if tg:
        keyring.set_password(config.KR_SERVICIO_TG, "token", tg["token"])
        keyring.set_password(config.KR_SERVICIO_TG, "chat_id", tg["chat_id"])
    print(f"Guardadas {len(datos.get('sol', {}))} Claves SOL"
          f"{' y Telegram' if tg else ''} en el Administrador de Credenciales de Windows.")
    print("Ya puedes BORRAR el archivo credenciales.cifradas de esta carpeta.")


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    {"exportar": exportar, "importar": importar}.get(accion, lambda: print(__doc__))()
