param([string]$RollbackRelease)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
if (-not (Test-Path -LiteralPath $paths.CurrentRoot -PathType Container)) {
    throw "PDI application is not installed."
}
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Scheduled task '$($paths.TaskName)' is not installed."
}
if (-not (Test-Path -LiteralPath $paths.RollbackRoot -PathType Container)) {
    throw "No previous application release is available to roll back."
}
if (-not $RollbackRelease) {
    $previous = Get-ChildItem -LiteralPath $paths.RollbackRoot -Directory |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $previous) {
        throw "No previous application release is available to roll back."
    }
    $RollbackRelease = $previous.FullName
}
$rollbackPath = (Resolve-Path -LiteralPath $RollbackRelease).Path
$rollbackRootPath = (Resolve-Path -LiteralPath $paths.RollbackRoot).Path.TrimEnd("\") + "\"
if (-not $rollbackPath.StartsWith($rollbackRootPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Rollback release must be a version directory under $($paths.RollbackRoot)."
}
if (-not (Test-Path -LiteralPath (Join-Path $rollbackPath "release.json") -PathType Leaf)) {
    throw "Selected rollback folder is not a valid PDI release."
}

$currentManifest = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
$currentPython = Get-PDIPythonPath -Version ([string]$currentManifest.version)
$wasRunning = $task.State -eq "Running"
try {
    $wasRunning = Stop-PDITaskAndWait
}
catch {
    if ($wasRunning) {
        Start-ScheduledTask -TaskName $paths.TaskName
    }
    throw
}

$backupPath = Join-Path $paths.BackupRoot (
    "before-rollback-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".zip"
)
$env:PDI_ENV_FILE = $paths.ConfigFile
$env:APP_ENV = "production"
$env:APP_VERSION = [string]$currentManifest.version
$env:HOST = "127.0.0.1"
$env:PORT = "8765"
try {
    Push-Location $paths.CurrentRoot
    try {
        & $currentPython -m backend.backup_cli backup --destination $backupPath
        if ($LASTEXITCODE -ne 0) {
            throw "Pre-rollback backup failed; application code was not changed."
        }
    }
    finally {
        Pop-Location
    }
}
catch {
    if ($wasRunning) {
        Start-ScheduledTask -TaskName $paths.TaskName
    }
    throw
}

$failedPath = Join-Path $paths.ProgramRoot (
    "failed-" + [string]$currentManifest.version + "-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
)
try {
    Move-Item -LiteralPath $paths.CurrentRoot -Destination $failedPath
}
catch {
    if ($wasRunning) {
        Start-ScheduledTask -TaskName $paths.TaskName
    }
    throw
}
try {
    Move-Item -LiteralPath $rollbackPath -Destination $paths.CurrentRoot
    Start-ScheduledTask -TaskName $paths.TaskName
    $startScript = Join-Path $paths.ToolsRoot "Start-PDI.ps1"
    & (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") `
        -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $startScript
    if ($LASTEXITCODE -ne 0) {
        throw "The previous release failed its local health check."
    }
    if (-not $wasRunning) {
        Stop-ScheduledTask -TaskName $paths.TaskName
    }
    Write-Output "Application code rolled back. Current business data was not rolled back."
    Write-Output "Pre-rollback backup: $backupPath"
    Write-Output "The replaced application code is preserved at $failedPath."
}
catch {
    $rollbackError = $_
    $runningTask = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
    if ($runningTask -and $runningTask.State -eq "Running") {
        Stop-ScheduledTask -TaskName $paths.TaskName
    }
    if (Test-Path -LiteralPath $paths.CurrentRoot) {
        Move-Item -LiteralPath $paths.CurrentRoot -Destination $rollbackPath
    }
    if (Test-Path -LiteralPath $failedPath) {
        Move-Item -LiteralPath $failedPath -Destination $paths.CurrentRoot
    }
    if ($wasRunning) {
        Start-ScheduledTask -TaskName $paths.TaskName
    }
    throw $rollbackError
}
