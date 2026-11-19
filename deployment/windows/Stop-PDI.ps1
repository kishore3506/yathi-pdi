$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if (-not $task -and -not (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)) {
    Write-Output "PDI scheduled task is not installed and its backend port is stopped."
    exit 0
}
$null = Stop-PDITaskAndWait
Write-Output "PDI backend task is stopped."
