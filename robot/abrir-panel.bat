@echo off
rem Doble clic para abrir el panel del Monitor SUNAT (sin ventana negra).
cd /d "%~dp0"
start "" pythonw.exe "%~dp0panel.py"
