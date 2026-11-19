$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output "Scheduled task '$($paths.TaskName)' is not installed."
    exit 0
}
if ($task) {
    $null = Stop-PDITaskAndWait
}
Unregister-ScheduledTask -TaskName $paths.TaskName -Confirm:$false
Write-Output "Scheduled task '$($paths.TaskName)' removed. Application and business data were not deleted."
