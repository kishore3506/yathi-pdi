$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
Assert-PDIHostConfigReady
$runner = Join-Path $paths.ToolsRoot "Run-Backend.ps1"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "Backend startup wrapper is missing: $runner"
}
if (-not (Test-Path -LiteralPath $paths.CurrentRoot -PathType Container)) {
    throw "Install the PDI release before registering its scheduled task."
}

$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument $arguments `
    -WorkingDirectory $paths.CurrentRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\LOCAL SERVICE" `
    -LogonType ServiceAccount `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $paths.TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Yathi Pumps PDI LAN backend; serves loopback only behind IIS HTTPS." `
    -Force | Out-Null

Write-Output "Scheduled task '$($paths.TaskName)' registered for Local Service at Windows startup."
Write-Output "No account password is stored. Local Service has only the file permissions granted by installation."
