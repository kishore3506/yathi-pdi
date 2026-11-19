$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if ($task) {
    Get-ScheduledTaskInfo -TaskName $paths.TaskName |
        Select-Object LastRunTime, LastTaskResult, NextRunTime
    Write-Output "Task state: $($task.State)"
}
else {
    Write-Output "Task state: not installed"
}

try {
    $health = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8765/api/health" `
        -TimeoutSec 5
    Write-Output "Backend health: healthy"
    $health | ConvertTo-Json -Depth 4
}
catch {
    Write-Output "Backend health: unavailable on 127.0.0.1:8765"
}

if (Test-Path -LiteralPath (Join-Path $paths.LogsRoot "pdi.log")) {
    Write-Output "Application log: $(Join-Path $paths.LogsRoot 'pdi.log')"
}
