# Monitor Buzón SOL SUNAT — Documentación técnica completa

> Documento de referencia para ingeniería. Describe arquitectura, cada módulo `.py`,
> decisiones de diseño y los puntos que un ingeniero informático debe conocer para
> mantener o extender el sistema.
> **Stack:** Python 3.14 · Playwright (Chromium/Chrome) · Tkinter · openpyxl · keyring · cryptography
> **Plataforma:** Windows 10/11 · **Dominio:** RPA de scraping autenticado + notificación push

---

## 1. Problema de ingeniería

Automatizar la lectura de un portal gubernamental autenticado (SUNAT SOL) para N cuentas,
detectar elementos nuevos de forma idempotente y notificar por un canal push, con tres
restricciones duras:

1. **Idempotencia estricta.** Un aviso duplicado erosiona la confianza del usuario; un aviso
   perdido tiene consecuencias legales (plazos tributarios). El sistema debe garantizar
   *exactly-once* desde la perspectiva del usuario, sobre un backend (SUNAT) sin API ni webhooks.
2. **Efectos secundarios prohibidos.** Leer no debe mutar el estado remoto: las notificaciones
   deben seguir marcadas como *no leídas* en SUNAT.
3. **Credenciales de alto valor.** 11 Claves SOL con acceso tributario completo. Nunca en texto
   plano, nunca a terceros.

## 2. Arquitectura

```
                      ┌──────────────┐
   Usuario ──────────►│  panel.py    │  Tkinter (hilo UI)
                      └──────┬───────┘
                             │ subprocess + pipe (stdout línea a línea)
                             ▼
                      ┌──────────────┐
                      │  robot.py    │  orquestador / CLI
                      └──┬────┬───┬──┘
          credenciales.py│    │   │reglas.py
         (keyring/cofre) │    │   │(parsing + prioridad)
                         ▼    ▼   ▼
                   sunat.py  registro.py  telegram.py
                  (Playwright) (Excel+JSON)  (Bot API)
```

**Separación de responsabilidades:** cada módulo tiene una única razón de cambio.
Si SUNAT rediseña su portal solo cambia `sunat.py`; si cambia el canal de aviso, solo
`telegram.py`; si cambia el formato de reporte, solo `registro.py`.

### Mapa de módulos

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `config.py` | Constantes y rutas. Sin lógica | — |
| `credenciales.py` | Acceso a secretos (keyring + fallback env) | config |
| `cofre.py` | Cifrado/descifrado de credenciales para transporte | config, credenciales, registro |
| `sunat.py` | Driver del portal: login, lectura, logout | config |
| `reglas.py` | Reglas de negocio: parsing de asunto, prioridad | — |
| `registro.py` | Persistencia: Excel (humano) + JSON (máquina) | config |
| `telegram.py` | Formato y envío de mensajes | credenciales |
| `robot.py` | Orquestación, CLI, deduplicación, concurrencia | todos |
| `panel.py` | GUI | config, registro, (robot vía subprocess) |
| `crear_portable.py` | Build del paquete de distribución | config |

---

## 3. `config.py` — configuración centralizada

Sin lógica: solo constantes. Las rutas se derivan de `Path(__file__)`, no del directorio de
trabajo, para que el programa funcione igual lanzado desde la GUI, desde el Programador de
tareas o desde una shell.

```python
RAIZ  = Path(__file__).resolve().parent.parent
ROBOT = Path(__file__).resolve().parent
```

**Punto crítico — `URL_LOGIN`.** El bug más costoso del proyecto vivió aquí. Entrar por
`e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm` dispara un flujo OAuth2 cuyo `redirect_uri`
retorna a `api-seguridad.sunat.gob.pe/?state=&code=...` con **`state` vacío**, y la página de
retorno ("Bienvenidos a SUNAT") no sabe a dónde continuar: callejón sin salida silencioso.

La URL correcta es la del menú real, que lleva un `state` serializado:

```
https://api-seguridad.sunat.gob.pe/v1/clientessol/{clientId}/oauth2/loginMenuSol
   ?originalUrl=https://e-menu.sunat.gob.pe/cl-ti-itmenu/AutenticaMenuInternet.htm
   &state=rO0ABXNy...
```

Ese `state` es un **`java.util.HashMap` serializado y codificado en Base64** (el prefijo
`rO0AB` es la firma de la serialización de Java). Decodificado contiene `exe=buzon` y la ruta
destino. Es decir, SUNAT transporta estado de navegación del lado servidor dentro del parámetro
OAuth. **Lección de ingeniería:** en un flujo OAuth2, `state` no siempre es solo anti-CSRF;
algunos backends lo usan como *continuation token*. Descartarlo rompe el flujo de forma
no evidente, porque el login sí tiene éxito (hay `code=`) pero la sesión nunca aterriza.

---

## 4. `credenciales.py` — gestión de secretos

Abstrae el origen del secreto detrás de dos funciones (`obtener_sol`, `obtener_telegram`), con
una cadena de resolución:

```python
def _secreto(servicio, clave, env):
    try:
        v = keyring.get_password(servicio, clave)   # 1º Windows Credential Manager
        if v: return v
    except Exception:
        pass
    return os.environ.get(env)                      # 2º variable de entorno (CI/cloud)
```

**Por qué este orden:** en la PC del usuario, el *Credential Manager* cifra con la cuenta de
Windows (DPAPI) — un atacante con el archivo pero sin la sesión no lo abre. En un entorno sin
escritorio (GitHub Actions) no existe ese almacén, y las variables de entorno son el mecanismo
estándar de inyección de secretos. Una sola abstracción cubre los dos mundos sin ramificar
el código llamador.

El formato almacenado es `"USUARIO|CLAVE"` bajo la clave `ruc`, lo que permite una entrada por
empresa en un único "servicio" de keyring.

---

## 5. `cofre.py` — criptografía para el transporte

Problema: entregar 11 credenciales a otra PC sin que viajen legibles.

```python
kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=sal, iterations=600_000)
f   = Fernet(base64.urlsafe_b64encode(kdf.derive(password.encode())))
```

Conceptos que el ingeniero debe reconocer:

- **KDF (PBKDF2-HMAC-SHA256).** Una contraseña humana tiene poca entropía; no sirve como clave
  criptográfica directa. El KDF la estira a 32 bytes y, con 600 000 iteraciones, encarece el
  ataque por fuerza bruta en varios órdenes de magnitud. El costo se paga una vez por apertura.
- **Salt aleatorio de 16 bytes**, antepuesto al blob (`sal + ciphertext`). Impide tablas
  precomputadas (rainbow tables): el mismo password produce claves distintas en cada exportación.
- **Fernet** = AES-128-CBC + HMAC-SHA256 (*encrypt-then-MAC*). Es **autenticado**: un
  ciphertext alterado falla con `InvalidToken` en vez de descifrar basura. Por eso una
  contraseña incorrecta y un archivo corrupto producen el mismo error controlado.
- **Separación de canales.** El archivo cifrado viaja en el USB; la contraseña maestra, por
  teléfono. Enviar ambos por el mismo medio anula el cifrado por completo.

El ciclo de vida termina con la destrucción del intermediario: tras `importar`, las claves
quedan en el keyring del destino y el `.cifradas` debe borrarse.

---

## 6. `sunat.py` — el driver del portal

El módulo más frágil por naturaleza: depende del HTML de un tercero.

### 6.1 Extracción resiliente con fallback estructural

```javascript
let nodos = [...document.querySelectorAll('.list-group-item')]
    .filter(n => reFecha.test(n.innerText) && unAsunto(n.innerText));
if (!nodos.length) {
  const cand = [...document.querySelectorAll('li, tr, div, a')]
      .filter(n => reFecha.test(n.innerText) && unAsunto(n.innerText));
  nodos = cand.filter(n => !cand.some(o => o !== n && n.contains(o)));
}
```

Dos estrategias en cascada:
1. **Selector conocido** (`.list-group-item`) — rápido y preciso mientras el HTML no cambie.
2. **Heurística estructural** — si el selector falla, busca cualquier nodo que *parezca* una
   tarjeta: contiene una fecha y exactamente un `ASUNTO:`. El filtro
   `!cand.some(o => n.contains(o))` se queda con los **nodos hoja**, descartando los
   contenedores padre que también cumplirían el patrón.

**Principio general:** acoplarse a la *semántica* del contenido (hay una fecha y un asunto)
sobrevive a los rediseños mucho mejor que acoplarse a nombres de clases CSS, que son detalle
de presentación.

### 6.2 Búsqueda en todos los frames

El buzón vive dentro de `<iframe>`s. El código itera `page.frames` y evalúa el extractor en
cada uno, tolerando excepciones por frame (uno puede recargarse a mitad de la iteración).
En Playwright, `page.frames` incluye el frame principal y todos los anidados.

### 6.3 Distinguir "vacío" de "roto"

Falla de diseño corregida durante el desarrollo: *cero resultados* es ambiguo. Puede significar
buzón vacío (normal) o extractor roto (grave). La desambiguación usa un **marcador de carga**:

```python
MARCAS_BUZON = ("buscar por asunto", "buzón notificaciones", "mis carpetas")
```

Si el marcador está presente y no hay tarjetas → buzón vacío → `OK` con 0 ítems.
Si no está → no llegamos a la página correcta → `CAMBIO_PAGINA`.

**Lección:** en todo scraper, un resultado vacío necesita una **señal positiva de que la página
correcta cargó**. Sin ella no se puede distinguir "no hay datos" de "fallé silenciosamente".

### 6.4 Máquina de estados del login

El bucle de login espera una de varias condiciones mutuamente excluyentes, con timeout global:

| Estado | Detección | Semántica |
|---|---|---|
| `OK` | URL contiene `e-menu.sunat.gob.pe` | Sesión establecida |
| *rescate* | URL con `api-seguridad` + `code=` | OAuth completó pero no continuó → navegar directo al buzón (una sola vez, con flag `rescatado`) |
| `CAPTCHA` | Existe `#txtCaptcha` | Intervención humana requerida; se aborta |
| `LOGIN_FALLIDO` | `#divMensajeError` | Credencial inválida |
| `SESION_ACTIVA` | Regex sobre el texto del body | Otra sesión abierta en ese RUC |
| 2FA | `#btnWithOutCode` | Se pulsa "continuar sin código" |
| `TIMEOUT` | Se agota el presupuesto | Sin respuesta |

El flag `rescatado` evita un bucle infinito de redirecciones: el rescate se intenta exactamente
una vez por sesión.

### 6.5 Taxonomía de errores y política de reintento

```python
except Exception as e:
    if "TargetClosed" in type(e).__name__ or "has been closed" in str(e):
        res = Resultado("VENTANA_CERRADA", ...)      # causa externa, no alarmar
    else:
        res = Resultado("ERROR", ...)
```

Los estados se dividen en **transitorios** (`SESION_ACTIVA`, `TIMEOUT`, `VENTANA_CERRADA`) y
**accionables** (`LOGIN_FALLIDO`, `CAPTCHA`, `CAMBIO_PAGINA`, `ERROR`). Solo los segundos
generan alerta. Clasificar los errores por *qué debe hacer el humano* —y no por su tipo
técnico— es lo que evita la fatiga de alertas.

### 6.6 Aislamiento y no mutación

- Un `BrowserContext` nuevo por empresa, cerrado al terminar: equivale a una ventana de
  incógnito. Sin cookies compartidas, sin contaminación entre cuentas.
- **Nunca se hace clic en una notificación.** Solo se lee la lista. Esto preserva el estado
  "no leído" en SUNAT, que es la señal de trabajo pendiente de la contadora.
- `_salir()` cierra sesión explícitamente para liberar el RUC (SUNAT permite una sesión por
  cuenta); va en `finally`, con su propio `try` porque la página puede ya no existir.

---

## 7. `reglas.py` — lógica de dominio

Aísla el conocimiento tributario del código técnico.

```python
RE_TIPO_NUM = re.compile(
    r"Notificaci[oó]n\s+(?:de\s+)?(?P<tipo>.+?)\s+N\s*\.?\s*[°º]\s*(?P<num>\d[\dA-Z-]{5,})", re.I)
```

Detalles que importan:
- `(?P<tipo>.+?)` es **no codicioso**: se detiene en el primer `N°`, evitando tragarse el número.
- La clase `[\dA-Z-]` admite números alfanuméricos (`003577020267E1600`, de las Esquelas) además
  de los numéricos con guiones (`024-003-0574990`). Una versión anterior solo aceptaba dígitos
  y truncaba silenciosamente los de Esquela — **bug de datos, no de ejecución**: el programa no
  fallaba, solo guardaba mal.
- `[°º]` cubre los dos caracteres de "grado" que SUNAT mezcla en sus asuntos.

La función `prioridad(etiqueta, asunto)` mapea a ALTA/MEDIA/BAJA combinando la etiqueta de
color de SUNAT con palabras del asunto. **Queda deliberadamente como punto de extensión**
(`TODO(human)`), porque la política de urgencia es una decisión del negocio, no técnica.

---

## 8. `registro.py` — persistencia dual

Dos almacenes con propósitos distintos, y esa dualidad es intencional:

| Almacén | Para | Propiedad clave |
|---|---|---|
| `data/vistos.json` | La máquina | Siempre escribible, escritura atómica |
| `REGISTRO-...xlsx` | La persona | Legible, filtrable, auditable |

### 8.1 Identidad de contenido (deduplicación)

```python
def hacer_id(ruc, fecha_txt, asunto):
    asunto = re.sub(r"\s+", " ", asunto).strip()      # normalización
    return hashlib.sha1(f"{ruc}|{fecha_txt}|{asunto}".encode()).hexdigest()[:12]
```

Es un **content-addressed identifier**: la identidad se deriva del contenido, no de la posición
ni de un correlativo. Ventajas sobre contar elementos (`total_actual - total_anterior`):

- Inmune a reordenamientos y a la paginación del portal.
- Inmune a borrados: si desaparece un elemento viejo, no se interpreta como "llegó uno nuevo".
- Permite reconstruir el estado desde el Excel si se pierde el JSON.

La normalización de espacios es indispensable: sin ella, un cambio de salto de línea en el HTML
genera un hash distinto y un aviso duplicado del mismo documento.

### 8.2 Escritura atómica

```python
tmp.write_text(...); tmp.replace(config.ESTADO_VISTOS)
```

`Path.replace` es atómico a nivel de sistema de archivos. Un corte de energía a mitad de
escritura deja el archivo anterior intacto en vez de un JSON truncado que rompería el arranque
siguiente. Patrón *write-temp-then-rename*.

### 8.3 Degradación elegante ante el Excel bloqueado

Windows bloquea el `.xlsx` mientras el usuario lo tiene abierto. En lugar de fallar:

```python
except PermissionError:
    PENDIENTES.write_text(json.dumps(lote, default=str))   # cola en disco
```

Las filas se encolan en `pendientes.jsonl` y se fusionan en la siguiente corrida. **El aviso de
Telegram nunca depende de que el Excel esté disponible**: el camino crítico (avisar) está
desacoplado del camino secundario (reportar).

---

## 9. `telegram.py` — notificación

HTTP con `urllib` de la biblioteca estándar: cero dependencias para el camino crítico.

```python
except urllib.error.HTTPError as e:
    if e.code == 429:
        espera = json.load(e).get("parameters", {}).get("retry_after", espera)
    elif e.code < 500: return False      # 4xx: error del cliente, no reintentar
time.sleep(espera); espera *= 2          # backoff exponencial
```

- **Backoff exponencial** con respeto al `retry_after` que envía el propio servidor.
- **No se reintentan los 4xx** (salvo 429): un token inválido no mejora con reintentos.
- **Escape de HTML obligatorio** (`html.escape`) en todo dato dinámico. Una razón social como
  `B & M S.A.C.` rompe el `parse_mode=HTML` si no se escapa el `&`. Es el mismo principio que
  prevenir inyección: nunca interpolar datos sin escapar en un formato con marcado.

Dos niveles de mensaje, por diseño de UX:
- **Detalle** por cada notificación nueva (qué llegó exactamente).
- **Resumen** por corrida, con las 11 empresas ordenadas por urgencia (novedades → errores →
  sin novedades). Un mensaje de 11 líneas en lugar de 11 mensajes: con 48 revisiones diarias,
  lo segundo sería 528 mensajes/día y el usuario dejaría de leerlos.

---

## 10. `robot.py` — orquestación

### 10.1 Exclusión mutua entre lanzadores

Existen dos disparadores (botón del panel y tarea de Windows). Dos corridas simultáneas
intentarían dos sesiones en el mismo RUC → `SESION_ACTIVA`.

```python
if lock.exists() and time.time() - lock.stat().st_mtime < 15*60:
    return False          # hay otra corrida viva
lock.write_text(...)      # candado con expiración
```

Lock de archivo **con expiración por antigüedad**, no permanente: si el proceso muere sin
liberarlo (kill, corte de luz), el candado caduca solo. Sin expiración, un crash dejaría el
sistema bloqueado para siempre — el fallo clásico de los locks ingenuos. El umbral (15 min)
se fija por encima de la duración máxima esperada (~6 min) con margen.

### 10.2 Carga inicial silenciosa

```python
primera_vez = empresa["ruc"] not in estado["rucs"]
callar = silencioso or primera_vez
```

La primera vez que se observa un buzón, su contenido se registra **sin notificar**. Sin esto,
dar de alta una empresa dispararía decenas de avisos históricos. Es el equivalente a
inicializar un *watermark* antes de empezar a emitir eventos. El flag es **por RUC**, no
global: dar de alta una empresa nueva meses después tampoco inunda el canal.

### 10.3 Confirmación antes de marcar como visto

```python
alertada = telegram.enviar(...)
if not alertada:
    continue              # NO se agrega a vistos → se reintenta la próxima vuelta
estado["ids"].add(nid)
```

El ID se registra **solo si Telegram confirmó la entrega**. Esto convierte un fallo de red en
*at-least-once* (posible aviso repetido) en vez de *at-most-once* (aviso perdido). En este
dominio la asimetría es clara: un duplicado molesta, un aviso perdido puede costar un plazo
tributario. **Elegir conscientemente la dirección del fallo** es una decisión de arquitectura.

El estado se persiste **después de cada empresa**, no al final: un corte a mitad de corrida no
pierde ni repite el trabajo ya hecho.

### 10.4 Alertas solo en transiciones

```python
previo = estado["ultimo"].get(ruc, "OK")
if res.estado != "OK" and res.estado != previo:   telegram.enviar(falla)
elif res.estado == "OK" and previo in AVISAR_FALLA: telegram.enviar(recuperado)
```

Se notifica el **cambio de estado**, no el estado. Con 48 corridas diarias, alertar en cada
una sobre una falla persistente produciría 48 mensajes idénticos. Es el patrón *edge-triggered*
frente a *level-triggered* de los sistemas de monitoreo, con su aviso de recuperación.

### 10.5 Heartbeat

Un resumen diario confirma que el sistema está vivo. **Un sistema que solo habla cuando hay
novedades es indistinguible de uno caído.** El heartbeat convierte el silencio en señal: si un
día no llega, algo se detuvo.

### 10.6 Robustez de E/S en Windows

```python
flujo.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
```

Bug real encontrado: al ejecutarse desde la GUI, `stdout` es un *pipe* y Python adopta la
codificación del sistema (**cp1252**), no UTF-8. El primer `print("→ ...")` lanzaba
`UnicodeEncodeError` y abortaba todo. La corrección es doble:
- El hijo reconfigura su propio `stdout` (defensa interna).
- El padre inyecta `PYTHONUTF8=1` en el entorno (defensa externa).

`line_buffering=True` además fuerza el *flush* por línea: sin él, la salida hacia un pipe se
almacena en búfer y la GUI mostraría todo de golpe al final en vez de en vivo.

---

## 11. `panel.py` — GUI y modelo de concurrencia

### 11.1 Tkinter no es thread-safe

Regla absoluta: **solo el hilo principal toca widgets.** El patrón implementado:

```
hilo trabajador → queue.Queue → root.after(200, bombear) → widgets
```

El trabajador lee el `stdout` del subproceso y publica en una cola. El hilo de UI la drena
periódicamente con `root.after`. Esto mantiene la interfaz responsiva sin ninguna llamada a
widgets desde el hilo secundario. Es el equivalente Tkinter del *event loop dispatch* de otros
toolkits.

### 11.2 Aislamiento por subproceso

El robot se ejecuta como proceso separado, no importado. Beneficios: un crash del robot no
tumba la GUI; se puede matar sin dejar la GUI inconsistente; y el mismo `robot.py` sirve a la
GUI, al Programador de tareas y a la línea de comandos sin cambios.

### 11.3 Cancelación y árbol de procesos

```python
subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)])
LOCK.unlink(missing_ok=True)
```

`terminate()` sobre el proceso padre dejaría **Chromium huérfano**, porque Playwright lo lanza
como hijo. `taskkill /T` elimina el árbol completo. Y como el robot muere sin ejecutar su
`finally`, la GUI libera el candado en su nombre. **Toda cancelación debe considerar los
recursos que el proceso muerto no alcanzó a liberar.**

---

## 12. Modelo de seguridad

| Activo | Protección en reposo | En tránsito |
|---|---|---|
| Claves SOL (uso normal) | DPAPI vía Windows Credential Manager | Solo al formulario de SUNAT por HTTPS |
| Claves SOL (distribución) | Fernet + PBKDF2 600k | USB; contraseña por canal separado |
| Token de Telegram | Credential Manager | HTTPS a api.telegram.org |
| Historial de notificaciones | Excel local | No sale de la red local |

**Superficie de exposición controlada por `.gitignore`:** `*.xlsx`, `*.cifradas`, `robot/data/`,
`robot/logs/` (los volcados HTML de depuración contienen contenido real del buzón),
`PORTABLE-CONTADORA/`. La documentación es publicable; los datos, nunca.

**Decisión explícita de no evadir controles.** SUNAT bloquea con `ERR_CONNECTION_RESET` los
navegadores que se identifican como `HeadlessChrome`. Se decidió **no falsear el User-Agent**
para eludir esa detección. El sistema opera con un navegador real visible, que es lo que el
portal acepta. El costo es que requiere una sesión de escritorio activa; el beneficio es no
depender de una evasión que puede romperse —o acarrear consecuencias— en cualquier momento.

---

## 13. Despliegue

| Modo | Mecanismo | Requisito |
|---|---|---|
| Manual | `python robot.py --visible` | Shell |
| Panel | `panel.py` + temporizador `root.after` | Panel abierto |
| Desatendido | Programador de tareas, repetición cada N min | Sesión de Windows iniciada |

El principal `Interactive` del Programador es obligatorio: DPAPI solo descifra con la sesión
del usuario, y el navegador visible necesita un escritorio. Una tarea "ejecutar aunque el
usuario no haya iniciado sesión" fallaría en ambos frentes.

---

## 14. Puntos de extensión y deuda técnica conocida

1. **`reglas.prioridad()`** — política de urgencia pendiente de definir por el negocio.
2. **Propuesta A (`PROPUESTA-A-correo/`)** — lector IMAP de las alertas por correo de SUNAT,
   construido y archivado. Es *event-driven* en vez de *polling*, no requiere credenciales SOL
   y puede correr en la nube. Bloqueado por un requisito organizacional: no existen buzones
   corporativos por empresa.
3. **Paginación** — solo se lee la primera página del buzón (25 ítems). Suficiente mientras la
   frecuencia de revisión sea alta, pero una pausa larga podría dejar ítems fuera de vista.
4. **Lock por antigüedad** — un lock por PID vivo sería más preciso que la expiración temporal.
5. **Sin tests automatizados** — la verificación fue manual y por simulación (HTML sintético,
   round-trip de cifrado, inyección de líneas en la cola de la GUI).

---

## 15. Glosario de conceptos aplicados

| Concepto | Dónde aparece |
|---|---|
| Content-addressed ID | `registro.hacer_id` — identidad por contenido, no por posición |
| Escritura atómica (write-temp-rename) | `registro.guardar_estado` |
| At-least-once vs at-most-once | Confirmación de Telegram antes de marcar visto |
| Edge-triggered vs level-triggered | Alertas solo en cambio de estado |
| Watermark / inicialización silenciosa | Carga inicial por RUC |
| Lock con expiración | `robot._tomar_lock` |
| KDF + salt + cifrado autenticado | `cofre.py` |
| Thread-safety por cola de mensajes | `panel.py` |
| Degradación elegante | Cola `pendientes.jsonl` si el Excel está bloqueado |
| Backoff exponencial | `telegram.enviar` |
| Fallback estructural en scraping | `sunat.JS_EXTRAER` |
| Señal positiva de carga | `sunat.MARCAS_BUZON` |
