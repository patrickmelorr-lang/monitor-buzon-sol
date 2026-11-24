"""Arma el paquete que se le entrega a la contadora.

    python cofre.py exportar        # 1º cifrar las claves (pide contraseña maestra)
    python crear_portable.py        # 2º armar la carpeta + ZIP

Produce  PORTABLE-CONTADORA/  (y su .zip) con el programa, el Excel y las claves CIFRADAS.
Se entrega por USB o carpeta compartida. La contraseña maestra va por otro canal.
NUNCA subir este paquete a GitHub ni enviarlo por correo junto con la contraseña.
"""

from __future__ import annotations
import shutil
import sys
import zipfile
from pathlib import Path

import config

DESTINO = config.RAIZ / "PORTABLE-CONTADORA"
DEL_ROBOT = ["config.py", "credenciales.py", "registro.py", "reglas.py", "robot.py",
             "sunat.py", "telegram.py", "panel.py", "cofre.py",
             "instalar_tarea.ps1", "abrir-panel.bat"]

INSTALAR_BAT = r"""@echo off
chcp 65001 >nul
title Instalacion - Monitor Buzon SOL SUNAT

rem Algunos programas (por ejemplo ZKBioTime, de control de asistencia) traen su propio
rem Python y dejan PYTHONHOME / PYTHONPATH apuntando a el para toda la maquina. Eso hace
rem que CUALQUIER otro Python arranque con la libreria equivocada y muera con errores como
rem "SRE module mismatch". Se limpian SOLO para esta ventana y sus procesos hijos; la
rem configuracion global del otro programa no se toca.
set PYTHONHOME=
set PYTHONPATH=

echo.
echo ==========================================================
echo   MONITOR DE NOTIFICACIONES SUNAT - Instalacion
echo ==========================================================
echo.

rem Puede haber VARIOS Python instalados y "python" apuntar al mas viejo.
rem El lanzador "py -3" elige siempre el mas nuevo, asi que se prueba primero.
set PYEXE=
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
if not errorlevel 1 set PYEXE=py -3
if not defined PYEXE (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
  if not errorlevel 1 set PYEXE=python
)

if not defined PYEXE (
  echo [X] No encuentro un Python 3.8 o superior desde esta ventana.
  echo.
  echo     Lo que SI encontre:
  for /f "delims=" %%p in ('where py 2^>nul') do echo        py     -^> %%p
  for /f "delims=" %%p in ('where python 2^>nul') do echo        python -^> %%p
  for /f "delims=" %%v in ('python -V 2^>^&1') do echo        version: %%v
  echo.
  echo     CAUSA MAS COMUN: estas ejecutando este archivo como ADMINISTRADOR.
  echo     Python suele instalarse "solo para mi usuario", y la cuenta de
  echo     Administrador NO lo ve. Esta instalacion NO necesita permisos de
  echo     administrador.
  echo.
  echo     SOLUCION 1 ^(la mas rapida^):
  echo        Cierra esta ventana y abre INSTALAR.bat con DOBLE CLIC normal,
  echo        sin "Ejecutar como administrador".
  echo.
  echo     SOLUCION 2 ^(si de verdad no hay Python^):
  echo        En PowerShell normal ^(NO administrador^):
  echo           winget install -e --id Python.Python.3.12
  echo        Luego CIERRA la ventana, abre una nueva y repite.
  echo.
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('%PYEXE% -V 2^>^&1') do set PYVER=%%v
echo [1/4] Python %PYVER% encontrado.
%PYEXE% -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 echo      Aviso: con Python %PYVER% funciona, pero se recomienda 3.10 o superior.

rem -E hace que Python ignore TODAS las variables PYTHON* del sistema. Es el seguro
rem definitivo contra un Python ajeno impuesto por otro programa.
echo [2/5] Creando entorno aislado propio...
if exist "%~dp0venv" rmdir /s /q "%~dp0venv"
%PYEXE% -E -m venv "%~dp0venv"
if errorlevel 1 ( echo [X] No pude crear el entorno aislado. & pause & exit /b 1 )

rem A partir de aqui NO se usa el Python del sistema, sino el del entorno propio:
rem tiene sus propias librerias y no se mezcla con las de ningun otro programa.
set VPY="%~dp0venv\Scripts\python.exe"

echo [3/5] Instalando componentes (puede tardar unos minutos)...
%VPY% -E -m pip install --quiet --upgrade pip
%VPY% -E -m pip install --quiet playwright openpyxl keyring cryptography
if errorlevel 1 ( echo [X] Fallo la instalacion de componentes. & pause & exit /b 1 )

echo [4/5] Preparando el navegador...
%VPY% -E -m playwright install chromium

echo [5/5] Abriendo el cofre de claves...
echo      Te pedira la CONTRASENA MAESTRA (te la dio el area de Tecnologia).
cd /d "%~dp0robot"
%VPY% -E cofre.py importar
if errorlevel 1 ( echo [X] No se pudieron cargar las claves. & pause & exit /b 1 )

echo.
echo ==========================================================
echo   LISTO. Abre el monitor con:  abrir-monitor.bat
echo ==========================================================
echo.
pause
"""

ABRIR_BAT = r"""@echo off
rem Aislar de un Python ajeno instalado por otro programa (ver INSTALAR.bat).
set PYTHONHOME=
set PYTHONPATH=
cd /d "%~dp0robot"

rem Se usa el Python del entorno aislado que creo INSTALAR.bat. "-E" ignora las
rem variables PYTHON* del sistema; "w" es la version sin ventana negra.
if exist "%~dp0venv\Scripts\pythonw.exe" (
  start "" "%~dp0venv\Scripts\pythonw.exe" -E "%~dp0robot\panel.py"
) else (
  echo No encuentro el entorno aislado. Ejecuta primero INSTALAR.bat
  pause
)
"""

LEEME = """# Monitor de Notificaciones SUNAT — Guía rápida

## Qué hace
Revisa el Buzón SOL de las empresas y **avisa por Telegram** cuando SUNAT deposita una
notificación nueva. Así ya no hay que entrar empresa por empresa todos los días.

## Instalación (una sola vez)
1. Copia esta carpeta completa al disco C: de tu PC (por ejemplo `C:\\MonitorSUNAT`).
2. Doble clic en **`INSTALAR.bat`**.
3. Te pedirá la **contraseña maestra**: es la que te dio el área de Tecnología por teléfono.
4. Al terminar, borra el archivo `robot\\credenciales.cifradas` (ya no hace falta).

## Uso diario
Doble clic en **`abrir-monitor.bat`**. Se abre el panel:

- **Empresas a revisar** — vienen todas marcadas. Puedes desmarcar las que no quieras.
- **🔍 Revisar ahora** — revisa y, al terminar, te llega el resumen por Telegram.
- **⛔ Cancelar** — corta la revisión si la necesitas detener.
- **Automático** — marca la casilla y elige cada cuánto. Revisa sola mientras el panel esté abierto.
- **Seguir aunque cierre ▸ Windows** — para que siga funcionando con el panel cerrado.

Mientras trabaja se abren y cierran ventanas de Chrome: **es normal, no las toques.**

## ¿Algo falla?

Abre **`SOLUCION-DE-PROBLEMAS.md`**, en esta misma carpeta. Está ordenado por el mensaje que
aparece en pantalla. Las dos causas más comunes:

- **No abras `INSTALAR.bat` como Administrador.** Doble clic normal.
- Tras instalar Python, **cierra todas las ventanas negras y abre una nueva.**

## Si una empresa no carga
Es normal y no rompe nada. SUNAT a veces va lento o pide una verificación.
- El monitor **no se detiene**: sigue con las demás y la reintenta en la próxima vuelta.
- Si una falla varias veces seguidas: **márcala sola** y dale *Revisar ahora*.
  De una en una casi siempre entra.

## Importante
- El monitor **solo mira la lista** del buzón; no abre las notificaciones, así que
  te siguen apareciendo como no leídas en SUNAT.
- Si estás dentro de SUNAT con esa misma empresa, el monitor **no te saca**: lo reintenta después.
- El aviso de Telegram dice qué empresa y qué llegó. **La notificación oficial sigue
  estando en el Buzón SOL**: hay que entrar a leerla ahí.
"""


def main() -> int:
    cifrado = config.ROBOT / "credenciales.cifradas"
    if not cifrado.exists():
        print("Falta el cofre de claves. Corre primero:\n   python cofre.py exportar")
        return 1

    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    (DESTINO / "robot").mkdir(parents=True)

    faltan = [n for n in DEL_ROBOT if not (config.ROBOT / n).exists()]
    if faltan:
        print("No encuentro:", ", ".join(faltan))
        return 1
    for nombre in DEL_ROBOT:
        shutil.copy2(config.ROBOT / nombre, DESTINO / "robot" / nombre)
    shutil.copy2(cifrado, DESTINO / "robot" / "credenciales.cifradas")
    shutil.copy2(config.EXCEL_REGISTRO, DESTINO / config.EXCEL_REGISTRO.name)

    (DESTINO / "INSTALAR.bat").write_text(INSTALAR_BAT, encoding="utf-8")
    (DESTINO / "abrir-monitor.bat").write_text(ABRIR_BAT, encoding="utf-8")
    (DESTINO / "LEEME-PRIMERO.md").write_text(LEEME, encoding="utf-8")

    # La guía de problemas viaja con el paquete: la contadora la necesita justo cuando
    # algo falla, que es cuando no puede consultar nada.
    guia = config.RAIZ / "SOLUCION-DE-PROBLEMAS.md"
    if guia.exists():
        shutil.copy2(guia, DESTINO / guia.name)
    else:
        print("AVISO: no encontre SOLUCION-DE-PROBLEMAS.md; el paquete ira sin la guia.")

    zip_path = config.RAIZ / "PORTABLE-CONTADORA.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in DESTINO.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(DESTINO.parent))

    n = sum(1 for f in DESTINO.rglob("*") if f.is_file())
    print(f"Paquete listo: {DESTINO.name}  ({n} archivos)")
    print(f"ZIP: {zip_path.name}  ({zip_path.stat().st_size // 1024} KB)")
    print("\nEntregar por USB o carpeta compartida. La contraseña maestra, por otro canal.")
    print("NO subir a GitHub (el .gitignore ya lo bloquea).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
