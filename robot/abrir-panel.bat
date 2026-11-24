@echo off
rem Doble clic para abrir el panel del Monitor SUNAT (sin ventana negra).
rem Se limpia un Python ajeno que otro programa pudiera imponer por variables de entorno.
set PYTHONHOME=
set PYTHONPATH=
cd /d "%~dp0"
start "" pythonw.exe "%~dp0panel.py"
