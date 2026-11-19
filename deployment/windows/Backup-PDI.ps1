param([string]$Destination)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$manifest = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
Set-PDIProcessEnvironment -ReleaseRoot $paths.CurrentRoot
$python = Get-PDIPythonPath -Version ([string]$manifest.version)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment is missing for release $($manifest.version)."
}

$arguments = @("-m", "backend.backup_cli", "backup")
if ($Destination) {
    $arguments += @("--destination", $Destination)
}
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
$wasRunning = $task -and $task.State -eq "Running"
$wasRunning = Stop-PDITaskAndWait

$backupExitCode = 1
try {
    Push-Location $paths.CurrentRoot
    try {
        & $python @arguments
        $backupExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($wasRunning) {
        $startScript = Join-Path $paths.ToolsRoot "Start-PDI.ps1"
        & (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") `
            -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $startScript
        if ($LASTEXITCODE -ne 0) {
            throw "Backup action ended, but the backend did not restart successfully."
        }
    }
}
if ($backupExitCode -ne 0) {
    throw "PDI backup failed with exit code $backupExitCode."
}
