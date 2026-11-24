# Registra el robot en el Programador de tareas de Windows.
#   Instalar (cada 30 min, 24 h):   powershell -ExecutionPolicy Bypass -File .\instalar_tarea.ps1
#   Otro intervalo:                 ... -File .\instalar_tarea.ps1 -Minutos 20
#   Despertar la PC si duerme:      ... -File .\instalar_tarea.ps1 -Despertar
#   Ver estado:                     Get-ScheduledTaskInfo -TaskName 'Monitor Buzon SOL SUNAT'
#   Quitar:                         ... -File .\instalar_tarea.ps1 -Quitar
param([int]$Minutos = 30, [switch]$Despertar, [switch]$Quitar)
$ErrorActionPreference = 'Stop'
$Nombre = 'Monitor Buzon SOL SUNAT'

if ($Quitar) {
    Unregister-ScheduledTask -TaskName $Nombre -Confirm:$false
    Write-Host "Tarea '$Nombre' eliminada."
    return
}

# pythonw.exe = Python sin ventana de consola (corre oculto)
$pyw = & python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"
if (-not (Test-Path $pyw)) { throw "No encontre pythonw.exe junto a python ($pyw)" }
$script = Join-Path $PSScriptRoot 'robot.py'

# --visible: navegador REAL (no oculto). SUNAT corta el navegador oculto, por eso se usa el visible.
# La ventana de Chrome aparecera en el escritorio durante la revision; es normal.
# -E hace que Python IGNORE las variables PYTHON* del sistema. Es imprescindible aqui:
# la tarea hereda el entorno de la sesion, y si otro programa dejo PYTHONHOME/PYTHONPATH
# apuntando a su propio Python, el nuestro cargaria la libreria equivocada y moriria.
$accion = New-ScheduledTaskAction -Execute $pyw -Argument "-E `"$script`" --visible --log" -WorkingDirectory $PSScriptRoot
$cada = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes $Minutos)
$alEntrar = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$opciones = @{
    StartWhenAvailable         = $true    # si la PC estuvo apagada, corre apenas pueda
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    MultipleInstances          = 'IgnoreNew'   # nunca dos robots a la vez
    ExecutionTimeLimit         = (New-TimeSpan -Minutes 25)
}
if ($Despertar) { $opciones.WakeToRun = $true }
$ajustes = New-ScheduledTaskSettingsSet @opciones

# Interactive: corre con tu sesion de Windows abierta. Es necesario para leer las claves
# del Administrador de Credenciales (otra cuenta o "sin sesion" no puede leerlas).
$quien = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger @($cada, $alEntrar) `
    -Settings $ajustes -Principal $quien -Force `
    -Description 'Revisa el Buzon SOL de las empresas con MONITOREAR=SI y avisa por Telegram lo nuevo.' | Out-Null

Write-Host "Tarea '$Nombre' instalada: cada $Minutos min, primera corrida en ~2 min."
Write-Host "Salida en: $(Join-Path $PSScriptRoot 'logs\robot.log')"
