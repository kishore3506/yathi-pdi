param(
    [Parameter(Mandatory = $true)]
    [string]$BackupArchive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if ($task -and $task.State -eq "Running") {
    throw "Stop the PDI backend task before restoring an initial backup."
}
$archive = (Resolve-Path -LiteralPath $BackupArchive).Path
$manifest = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
Set-PDIProcessEnvironment -ReleaseRoot $paths.CurrentRoot
$python = Get-PDIPythonPath -Version ([string]$manifest.version)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment is missing for release $($manifest.version)."
}

Write-Warning "Initial restore imports records into the current database only when it has no business records."
Write-Warning "It does not replace existing records; if records already exist, the import will stop without changing them."
$confirmation = Read-Host "Type RESTORE to continue"
if ($confirmation -cne "RESTORE") {
    Write-Output "Restore cancelled."
    exit 0
}

Push-Location $paths.CurrentRoot
try {
    & $python -m backend.backup_cli restore-initial $archive
    if ($LASTEXITCODE -ne 0) {
        throw "Initial restore failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
