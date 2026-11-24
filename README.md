# Monitor Buzón SOL — SUNAT

Vigila los Buzones Electrónicos SOL de varias empresas y **avisa por Telegram** cuando SUNAT
deposita una notificación nueva.

📖 **Documentación:** [sitio del proyecto](https://USUARIO.github.io/REPOSITORIO/) ·
[Documentación técnica](TECNICO-NOTEBOOKLM.md)

---

## ⚠️ Antes de publicar este repositorio

Este proyecto maneja **credenciales tributarias de 11 empresas**. El archivo `.gitignore`
bloquea todo lo sensible, pero verifica siempre antes del primer `push`:

```bash
git status --short          # NO debe aparecer ningún .xlsx, .cifradas, data/ ni logs/
```

**Nunca se publica:** Claves SOL, el token de Telegram, los archivos `.xlsx` (llevan RUC e
historial), `robot/data/`, `robot/logs/` (volcados HTML del buzón real) ni
`PORTABLE-CONTADORA/` (contiene las credenciales cifradas).

## Estructura

```
robot/                     Propuesta B — el monitor en uso
  config.py                constantes y rutas
  credenciales.py          secretos (Windows Credential Manager)
  cofre.py                 cifra/descifra credenciales para transporte
  sunat.py                 login y lectura del buzón (Playwright)
  reglas.py                tipo, número y prioridad de cada notificación
  registro.py              Excel + estado anti-duplicados
  telegram.py              envío de avisos
  robot.py                 orquestador / CLI
  panel.py                 interfaz gráfica (Tkinter)
  crear_portable.py        arma el paquete para la contadora
  instalar_tarea.ps1       tarea programada de Windows
PROPUESTA-A-correo/        alternativa por correo IMAP (archivada)
docs/                      sitio público (GitHub Pages)
```

## Puesta en marcha

```powershell
cd robot
python credenciales.py migrar      # claves -> Administrador de Credenciales de Windows
python credenciales.py telegram    # token y chat_id del bot
python robot.py --prueba-telegram  # prueba de conexión
```

Uso diario: doble clic en `robot\abrir-panel.bat`.

## Entregar a otra PC

```powershell
cd robot
python cofre.py exportar           # cifra las claves con una contraseña maestra
python crear_portable.py           # arma PORTABLE-CONTADORA + .zip
```

Se entrega por USB. **La contraseña maestra va por otro canal** (teléfono o en persona),
nunca junto al paquete.

## Requisitos

Python 3.11+ · `playwright openpyxl keyring cryptography` · Google Chrome o Chromium ·
Windows con sesión iniciada (el navegador debe ser visible: SUNAT bloquea los navegadores ocultos).
