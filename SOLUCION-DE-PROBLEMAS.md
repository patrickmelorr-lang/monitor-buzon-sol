# Solución de problemas — Monitor Buzón SOL

Guía para resolver los fallos más comunes sin esperar al área de Tecnología.
Busca el mensaje que te aparece en pantalla; están escritos tal como salen.

**Dos reglas que resuelven la mitad de los casos:**

1. **Nunca abras `INSTALAR.bat` como Administrador.** Doble clic normal. Esta instalación
   no necesita permisos especiales, y usarlos causa la mayoría de los fallos.
2. **Después de instalar Python, cierra TODAS las ventanas negras y abre una nueva.**
   Windows solo actualiza su configuración en ventanas nuevas.

---

# A. Durante la instalación (`INSTALAR.bat`)

### A1 · "No encuentro un Python 3.8 o superior desde esta ventana"

**Por qué:** casi siempre, porque abriste el archivo **como Administrador**. Python se
instala "solo para mi usuario", y la cuenta de Administrador es para Windows *otro usuario
distinto*: no ve ese Python.

**Solución:**
1. Cierra la ventana.
2. Abre `INSTALAR.bat` con **doble clic normal**.

Si de verdad no hay Python, instálalo desde PowerShell **normal** (no Administrador):
```
winget install -e --id Python.Python.3.12
```
Luego cierra esa ventana, abre una nueva y repite la instalación.

> El instalador te muestra qué encontró y en qué ruta. Si pides ayuda, manda esa pantalla:
> dice exactamente cuál es el problema.

### A2 · "Tu Python es demasiado antiguo (se necesita 3.8 o superior)"

**Por qué:** la PC tiene una versión vieja de Python (por ejemplo 3.7).

**Solución:** instala Python 3.12 con el comando de arriba. **No desinstales el viejo**:
otros programas de la PC pueden estar usándolo. Conviven sin problema, y el monitor elige
solo el más nuevo.

### A3 · Se abre la Microsoft Store al escribir `python`

**Por qué:** Windows trae un acceso directo falso a Python que lleva a la tienda.

**Solución:** usa `py` en lugar de `python`. Para quitar el atajo falso:
Configuración → Aplicaciones → **Alias de ejecución de aplicaciones** → apaga las dos
entradas que digan *python.exe* y *python3.exe*.

### A4 · "Fallo la instalacion de componentes"

**Por qué:** no hay internet, o la red de la oficina bloquea la descarga.

**Solución:**
1. Comprueba que la PC navegue por internet.
2. Si la oficina usa proxy, pídele al área de Tecnología que lo configure para `pip`.
3. Vuelve a ejecutar `INSTALAR.bat`: retoma donde quedó, no daña nada.

### A5 · "Contraseña incorrecta o archivo dañado"

**Por qué:** la contraseña maestra no coincide, o el archivo `credenciales.cifradas` se copió
a medias.

**Solución:**
1. Escríbela a mano, sin copiar y pegar (el pegado suele arrastrar un espacio invisible).
   **Distingue mayúsculas de minúsculas.**
2. Al escribirla **no se ve nada en pantalla**: es normal, sigue escribiendo y pulsa Enter.
3. Si sigue fallando, vuelve a copiar la carpeta completa desde el USB y repite.

### A6 · "No encuentro credenciales.cifradas junto a estos archivos"

**Por qué:** se copió la carpeta incompleta, o ya se borró el archivo tras una instalación
anterior (es lo correcto, pero entonces las claves ya están cargadas).

**Solución:** si ya instalaste antes en esta PC, no hace falta repetir este paso: abre
directamente `abrir-monitor.bat`. Si es la primera vez, vuelve a copiar la carpeta del USB.

### A7 · "SRE module mismatch" o "Failed to import the site module"

El error completo menciona la carpeta de **otro programa**, por ejemplo:
```
Error processing line 1 of C:\ZKBioTime\Python37\Lib\site-packages\...
Fatal Python error: init_import_site: Failed to import the site module
AssertionError: SRE module mismatch
```

**Por qué:** hay otro programa en la PC que trae su propio Python (en este caso **ZKBioTime**,
el control de asistencia) y dejó las variables `PYTHONHOME` o `PYTHONPATH` apuntando a su
carpeta **para toda la máquina**. Cuando arranca cualquier otro Python, carga la librería
equivocada y muere. No es un fallo del monitor ni de tu instalación.

**Solución:** el `INSTALAR.bat` y el `abrir-monitor.bat` ya limpian esas variables solos.
Si ejecutas comandos a mano, límpialas primero en esa ventana:

```
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
```

**No borres esas variables de forma permanente** ni toques el Python del otro programa:
lo dejarías sin funcionar. El monitor se aísla por su cuenta y ambos conviven sin problema.

### A8 · El antivirus bloquea el archivo

**Por qué:** algunos antivirus desconfían de los `.bat` descargados.

**Solución:** pide al área de Tecnología que autorice la carpeta `C:\PORTABLE-CONTADORA`.
No ejecutes nada que no venga de ellos.

---

# B. Al abrir el panel (`abrir-monitor.bat`)

### B1 · No pasa nada, no se abre ninguna ventana

**Por qué:** la instalación no llegó a terminar, o se está usando el Python viejo.

**Solución:** vuelve a ejecutar `INSTALAR.bat` (doble clic normal) y mira si termina con
*LISTO*. Para ver el error oculto, abre PowerShell en la carpeta y escribe:
```
py -3 robot\panel.py
```
Lo que salga en rojo es la pista; mándalo a Tecnología.

### B2 · "No pude leer el Excel"

**Por qué:** falta `REGISTRO-NOTIFICACIONES-SUNAT.xlsx`, o está abierto en Excel.

**Solución:** cierra el Excel y reabre el panel. El archivo debe estar en la carpeta
principal, **al lado** de `abrir-monitor.bat`, no dentro de `robot`.

### B3 · La lista de empresas aparece vacía

**Por qué:** el Excel no tiene empresas marcadas, o se abrió otro archivo.

**Solución:** abre el Excel, hoja **EMPRESAS**, y revisa que la columna *MONITOREAR* diga
`SÍ`. Guarda, cierra y reabre el panel.

---

# C. Durante una revisión

> **Lo primero: que una empresa falle es normal y no rompe nada.** El monitor sigue con las
> demás y la reintenta sola en la próxima vuelta. Solo preocúpate si **la misma** empresa
> falla varias veces seguidas.

### C1 · `SESION_ACTIVA`

**Significa:** alguien está dentro de SUNAT con esa misma empresa (puede ser la propia
contadora en otra pestaña).

**Qué hacer:** nada. El monitor **no te saca** de tu sesión a propósito; lo reintenta
después. Si quieres que entre ya, cierra tu sesión de SUNAT de esa empresa.

### C2 · `CAPTCHA`

**Significa:** SUNAT pidió una verificación que solo una persona puede resolver.

**Qué hacer:** entra a esa empresa a mano esta vez. Si pasa seguido, avisa a Tecnología para
espaciar las revisiones (por ejemplo, de cada 30 minutos a cada hora).

### C3 · `TIMEOUT`

**Significa:** SUNAT tardó demasiado en responder.

**Qué hacer:** nada, se reintenta solo. Si le pasa a todas las empresas, probablemente el
portal de SUNAT esté caído o lento.

### C4 · `VENTANA_CERRADA`

**Significa:** se cerró la ventana de Chrome mientras trabajaba.

**Qué hacer:** **no cierres las ventanas de Chrome** que se abren solas durante la revisión.
Déjalas trabajar; se cierran por su cuenta.

### C5 · `LOGIN_FALLIDO`

**Significa:** SUNAT rechazó el usuario o la clave de esa empresa.

**Qué hacer:** comprueba entrando a mano a SUNAT con esa empresa. Si la clave cambió, avisa a
Tecnología para actualizarla; el monitor no puede adivinarla.

### C6 · `CAMBIO_PAGINA`

**Significa:** entró, pero no encontró la lista de notificaciones.

**Qué hacer:** avisa a Tecnología. Suele indicar que SUNAT cambió el diseño de su página y
hay que ajustar el programa.

### C7 · "Ya hay una revisión en curso. No arranco otra."

**Por qué:** otra revisión sigue trabajando, o una anterior se cortó de golpe.

**Qué hacer:** espera unos minutos. El bloqueo se libera solo a los 15 minutos. Si tienes
prisa, pulsa **⛔ Cancelar** en el panel: también lo libera.

### C8 · Se abren muchas ventanas de Chrome

**Por qué:** es el funcionamiento normal: una por empresa, en turnos.

**Qué hacer:** nada, y **no las toques**. Si te estorban, revisa menos empresas a la vez
desmarcando algunas en el panel.

---

# D. Telegram

### D1 · No llega ningún mensaje

**Revisa en orden:**
1. En el panel, pulsa **Probar Telegram**. Si llega el mensaje de prueba, la conexión está
   bien y simplemente no hay notificaciones nuevas.
2. Si no llega, comprueba que el bot siga dentro del grupo y que nadie lo haya expulsado.
3. Revisa que la PC tenga internet.

### D2 · La primera revisión no avisó nada

**Es a propósito.** La primera vez que se revisa una empresa, el monitor guarda lo que ya
había **sin avisar**. Si no, llegarían decenas de mensajes de notificaciones viejas. Desde la
segunda revisión avisa todo lo nuevo.

### D3 · Llegó dos veces el mismo aviso

**Por qué:** se cortó internet justo al enviar y el monitor lo reintentó.

**Está hecho a propósito:** se prefiere un aviso repetido antes que uno perdido. Un plazo
vencido cuesta mucho más que un mensaje de más.

---

# E. Si nada de esto funciona

Manda al área de Tecnología estos tres datos. Con eso se diagnostica casi todo:

1. **Captura de pantalla completa** del error, **incluyendo el título de la ventana**
   (ahí se ve si dice "Administrador").
2. El archivo `robot\logs\robot.log`, si existe.
3. En el Excel, la hoja **LOG_REVISIONES**: dice qué pasó en cada intento y a qué hora.

---

## Recordatorio importante

El monitor es una **ayuda**, no un reemplazo. La notificación de SUNAT es válida desde que se
deposita en el buzón, **llegue o no el aviso de Telegram**. Ante cualquier duda, la fuente
oficial siempre es el Buzón SOL.
