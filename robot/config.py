"""Rutas y constantes del monitor de Buzón SOL."""

from __future__ import annotations
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # carpeta NOTIFICACIONES-SUNAT
ROBOT = Path(__file__).resolve().parent

EXCEL_CLAVES = RAIZ / "CLAVE SOL.xlsx"                  # solo se lee en la migración
EXCEL_REGISTRO = RAIZ / "REGISTRO-NOTIFICACIONES-SUNAT.xlsx"
ESTADO_VISTOS = ROBOT / "data" / "vistos.json"          # fuente de verdad anti-duplicados
DIR_LOGS = ROBOT / "logs"

# Administrador de Credenciales de Windows (keyring)
KR_SERVICIO_SOL = "sunat-sol"                           # usuario = RUC, secreto = "USUARIO|CLAVE"
KR_SERVICIO_TG = "sunat-monitor-telegram"               # claves: "token", "chat_id"
KR_SERVICIO_CORREO = "sunat-monitor-correo"             # usuario = email, secreto = app password

# --- Propuesta A: lectura del correo de alerta de SUNAT ---
CORREO_IMAP = "imap.gmail.com"                           # Gmail; para Outlook: outlook.office365.com
CORREO_PUERTO = 993
# Filtro por remitente. SUNAT manda desde el dominio sunat.gob.pe; el buzón concreto se CONFIRMA
# con un correo real (ver LEEME: "Propuesta A"). Dejar el dominio es seguro: no perdemos correos.
REMITENTES_SUNAT = ["sunat.gob.pe"]
CORREO_DIAS_ATRAS = 3                                     # al arrancar, cuántos días mirar hacia atrás

URL_MENU = "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm"
URL_BUZON = URL_MENU + "?pestana=*&agrupacion=*&exe=buzon"

# Entrada de login CON "state" (la de LINKS.txt). Es importante: si se entra por MenuInternet.htm
# pelado, SUNAT devuelve a api-seguridad.sunat.gob.pe/?state=&code=... y se queda en la pantalla
# "Bienvenidos a SUNAT" sin seguir al menú. El state le dice a dónde continuar (buzón).
URL_LOGIN = (
    "https://api-seguridad.sunat.gob.pe/v1/clientessol/4f3b88b3-d9d6-402a-b85d-6a0bc857746a"
    "/oauth2/loginMenuSol?originalUrl=https://e-menu.sunat.gob.pe/cl-ti-itmenu/"
    "AutenticaMenuInternet.htm&state=rO0ABXNyABFqYXZhLnV0aWwuSGFzaE1hcAUH2sHDFmDRAwACRgAKbG9hZEZhY3R"
    "vckkACXRocmVzaG9sZHhwP0AAAAAAAAx3CAAAABAAAAADdAAEZXhlY3B0AAZwYXJhbXN0AEsqJiomL2NsLXRpLWl0bWVudS"
    "9NZW51SW50ZXJuZXQuaHRtJmI2NGQyNmE4YjVhZjA5MTkyM2IyM2I2NDA3YTFjMWRiNDFlNzMzYTZ0AANleGV0AAVidXpvbng="
)

TIMEOUT_MS = 45_000
PAUSA_ENTRE_EMPRESAS_S = 20                             # no golpear a SUNAT con logins seguidos
HORA_LATIDO = 8                                         # resumen diario "sigo vivo" desde las 08:00
