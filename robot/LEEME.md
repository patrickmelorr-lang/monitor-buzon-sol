# Robot Buzón SOL → Telegram (piloto)

| Archivo | Qué hace |
|---|---|
| `robot.py` | Orquesta: lee EMPRESAS del Excel, revisa cada RUC, alerta lo nuevo, escribe el Excel |
| `sunat.py` | Login SOL → lista del buzón → Salir. **Nunca abre una notificación** |
| `reglas.py` | Tipo y N° de documento desde el asunto; prioridad ALTA/MEDIA/BAJA |
| `registro.py` | Excel + `data/vistos.json` (anti-duplicados) + cola si el Excel está abierto |
| `telegram.py` | Envío con reintentos |
| `credenciales.py` | Claves SOL y token en el Administrador de Credenciales de Windows |

## Puesta en marcha (lo ejecuta una persona, desde esta carpeta)

1. **Credenciales** → `python credenciales.py migrar` y luego `python credenciales.py verificar`.
   Después, quitar la columna de claves de `CLAVE SOL.xlsx`.
2. **Bot de Telegram**
   - En Telegram, @BotFather → `/newbot` → copiar el token.
   - Crear el grupo "Notificaciones SUNAT", agregar al bot y a la contadora y escribir "hola" en el grupo.
   - Abrir en el navegador `https://api.telegram.org/bot<TOKEN>/getUpdates` y copiar `chat.id` (empieza con `-100…`).
   - `python credenciales.py telegram` → `python robot.py --prueba-telegram`
3. **Explorar 1 RUC con el navegador visible** → `python robot.py --explorar --ruc 20XXXXXXXXX`
   (capturas y HTML en `logs/`: sirven para ajustar los selectores si SUNAT cambió algo).
4. **Piloto** → `python robot.py`: revisa las empresas con `MONITOREAR = SÍ`. La 1ª vez registra
   sin alertar; desde la 2ª, alerta lo nuevo.

## Panel para la contadora (lo más fácil)

Doble clic en **`abrir-panel.bat`** (o `python panel.py`). Abre una ventana con:
- **Lista de empresas con casillas** — por defecto las 11 marcadas; se puede elegir cuáles revisar.
- **🔍 Revisar ahora** — revisa las marcadas y avisa por Telegram al terminar.
- **⛔ Cancelar** — corta la revisión en curso, cierra Chrome y libera el candado.
- **Automático** — casilla + cada cuánto (30 min / 1 h / 2 h). Revisa sola mientras el panel esté abierto.
- **Dejar corriendo aunque cierre ▸ Windows** — instala la tarea del Programador (sigue con el panel cerrado).
- **Probar Telegram** y un registro en vivo de lo que va pasando.

El botón del panel y la tarea de Windows **nunca se pisan**: hay un candado (`data/robot.lock`).

## Automático (Programador de tareas)

```powershell
powershell -ExecutionPolicy Bypass -File .\instalar_tarea.ps1          # cada 30 min, 24 h
```
- Corre oculto (`pythonw`); la salida va a `logs/robot.log`.
- Necesita la PC **encendida y con tu sesión de Windows abierta** (bloqueada sirve; suspendida no, salvo con `-Despertar`).
- Cada día desde las 08:00 llega un **resumen "Monitor activo"**. Si un día no llega, el robot está caído.
- Las fallas se avisan **una vez** cuando aparecen y otra cuando se recuperan, no en cada vuelta.

> **Esta carpeta es la PROPUESTA B** (entra al portal SOL). La Propuesta A (correo) está aparte,
> en `../PROPUESTA-A-correo/`, guardada para más adelante: hoy no hay correos corporativos por empresa.

## Estados en LOG_REVISIONES
`OK` · `LOGIN_FALLIDO` · `CAPTCHA` · `SESION_ACTIVA` (la contadora estaba dentro: se reintenta, no se la saca)
· `TIMEOUT` · `CAMBIO_PAGINA` (entró pero no halló la lista → correr `--explorar`) · `ERROR`.
LOGIN_FALLIDO, CAPTCHA, CAMBIO_PAGINA y ERROR mandan un ⚠️ por Telegram.

`data/` y `logs/` contienen datos tributarios: no subir a ningún repositorio ni nube.
