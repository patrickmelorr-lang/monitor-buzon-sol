# Propuesta A — correo de alerta de SUNAT → Telegram (GUARDADA PARA DESPUÉS)

**No está en uso.** Hoy no hay un correo corporativo por empresa, y la contadora prefiere no
depender de ese canal. La solución activa es la **Propuesta B** (carpeta `../robot/`).

Se guarda aquí lista para el día que existan esos correos.

## Cómo funcionaría
SUNAT manda un correo al email registrado en la ficha RUC cada vez que deposita una notificación.
`correo.py` lee ese buzón por IMAP (**no entra al portal**, por eso no choca con el bloqueo) y avisa
por Telegram. Reutiliza los módulos de `../robot/` (config, credenciales, telegram, registro).

- **Cada correo = una notificación nueva.** Anti-duplicado: el `Message-ID` del correo.
- Corre solo sin PC encendida: `alertas-correo.yml` (GitHub Actions, repo privado).

## Para activarla (futuro)
1. Un buzón corporativo (ej. Gmail) registrado en la ficha RUC de cada empresa.
2. App password del buzón → `python credenciales.py correo` (desde `../robot/`).
3. `python correo.py --prueba` (muestra lo que leería) → `python correo.py` (avisa).
4. Nube opcional: copiar `alertas-correo.yml` a `.github/workflows/` con secrets `TG_*` y `CORREO_*`.

⚠️ Falta confirmar con 1 correo real el remitente exacto de SUNAT (hoy filtra por dominio
`sunat.gob.pe` en `../robot/config.py`) y si trae el asunto o solo un aviso genérico.
