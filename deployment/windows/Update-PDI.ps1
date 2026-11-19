param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseArchive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
$archive = (Resolve-Path -LiteralPath $ReleaseArchive).Path
if (-not (Test-Path -LiteralPath $paths.CurrentRoot -PathType Container)) {
    throw "PDI is not installed. Use Install-PDIHost.ps1 for the first release."
}
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Scheduled task '$($paths.TaskName)' is not installed."
}

$stage = Join-Path $paths.ProgramRoot ("update-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
$oldRelease = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
$oldPython = Get-PDIPythonPath -Version ([string]$oldRelease.version)
$oldMovedPath = $null
$wasRunning = $task.State -eq "Running"
try {
    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    foreach ($requiredPath in @(
        "release.json",
        "backend\requirements.lock",
        "frontend\dist\index.html",
        "deployment\windows\Run-Backend.ps1"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $requiredPath))) {
            throw "Release archive is missing $requiredPath."
        }
    }

    $newRelease = Get-Content -LiteralPath (Join-Path $stage "release.json") -Raw | ConvertFrom-Json
    $newVersion = [string]$newRelease.version
    if ($newVersion -notmatch '^[A-Za-z0-9._-]+$' -or $newVersion -eq [string]$oldRelease.version) {
        throw "The release version is invalid or matches the installed release."
    }
    $newPython = Get-PDIPythonPath -Version $newVersion

    $oldAssets = Join-Path $paths.CurrentRoot "frontend\dist\assets"
    $newAssets = Join-Path $stage "frontend\dist\assets"
    if ((Test-Path -LiteralPath $oldAssets) -and (Test-Path -LiteralPath $newAssets)) {
        Get-ChildItem -LiteralPath $oldAssets -File | ForEach-Object {
            $destination = Join-Path $newAssets $_.Name
            if (Test-Path -LiteralPath $destination) {
                $oldHash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
                $newHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
                if ($oldHash -ne $newHash) {
                    throw "Release asset name collision detected; the old release remains active."
                }
            }
            else {
                Copy-Item -LiteralPath $_.FullName -Destination $destination
            }
        }
    }

    $pythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if (-not $pythonLauncher) {
        throw "Python Launcher was not found; install Python 3.12 x64 for all users."
    }
    if (-not (Test-Path -LiteralPath $newPython)) {
        & $pythonLauncher.Source -3.12 -m venv (Join-Path $paths.VenvRoot $newVersion)
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the Python environment for release $newVersion."
        }
    }
    & $newPython -m pip install --disable-pip-version-check -r (Join-Path $stage "backend\requirements.lock")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed; the installed release was not changed."
    }

    $wasRunning = Stop-PDITaskAndWait

    $backupPath = Join-Path $paths.BackupRoot (
        "before-update-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + ".zip"
    )
    if (-not (Test-Path -LiteralPath $oldPython)) {
        throw "The installed Python environment is missing; cannot create a pre-update backup."
    }
    $env:PDI_ENV_FILE = $paths.ConfigFile
    $env:APP_ENV = "production"
    $env:APP_VERSION = [string]$oldRelease.version
    $env:HOST = "127.0.0.1"
    $env:PORT = "8765"
    Push-Location $paths.CurrentRoot
    try {
        & $oldPython -m backend.backup_cli backup --destination $backupPath
        if ($LASTEXITCODE -ne 0) {
            throw "The required pre-update business-data backup failed; update was cancelled."
        }
    }
    finally {
        Pop-Location
    }

    $rollbackName = ([string]$oldRelease.version) + "-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
    $rollbackPath = Join-Path $paths.RollbackRoot $rollbackName
    New-Item -ItemType Directory -Path $paths.RollbackRoot -Force | Out-Null
    Move-Item -LiteralPath $paths.CurrentRoot -Destination $rollbackPath
    $oldMovedPath = $rollbackPath
    Move-Item -LiteralPath $stage -Destination $paths.CurrentRoot

    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
    & $icacls $paths.CurrentRoot /grant "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant the service account access to the new release."
    }
    & $icacls (Join-Path $paths.VenvRoot $newVersion) /inheritance:r | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not restrict the new virtual environment." }
    & $icacls (Join-Path $paths.VenvRoot $newVersion) /grant:r `
        "SYSTEM:(OI)(CI)F" `
        "BUILTIN\Administrators:(OI)(CI)F" `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set virtual-environment permissions." }

    Start-ScheduledTask -TaskName $paths.TaskName
    $startScript = Join-Path $paths.ToolsRoot "Start-PDI.ps1"
    & (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe") `
        -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $startScript
    if ($LASTEXITCODE -ne 0) {
        throw "New release failed its local health check."
    }
    if (-not $wasRunning) {
        Stop-ScheduledTask -TaskName $paths.TaskName
    }

    Get-ChildItem -LiteralPath (Join-Path $paths.CurrentRoot "deployment\windows") -Filter "*.ps1" |
        Copy-Item -Destination $paths.ToolsRoot -Force
    Write-Output "Release $newVersion is installed. Pre-update backup: $backupPath"
    Write-Output "Previous application code remains at $rollbackPath. Business data was kept in ProgramData."
}
catch {
    $updateError = $_
    if ($oldMovedPath -and (Test-Path -LiteralPath $oldMovedPath)) {
        $runningTask = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
        if ($runningTask -and $runningTask.State -eq "Running") {
            Stop-ScheduledTask -TaskName $paths.TaskName
            Start-Sleep -Seconds 2
        }
        $failedPath = Join-Path $paths.ProgramRoot (
            "failed-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
        )
        if (Test-Path -LiteralPath $paths.CurrentRoot) {
            Move-Item -LiteralPath $paths.CurrentRoot -Destination $failedPath
        }
        Move-Item -LiteralPath $oldMovedPath -Destination $paths.CurrentRoot
        Write-Warning "The update failed; previous code was restored. The failed release is preserved at $failedPath."
    }
    if ($wasRunning) {
        $runningTask = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
        if ($runningTask -and $runningTask.State -ne "Running") {
            Start-ScheduledTask -TaskName $paths.TaskName
        }
    }
    throw $updateError
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
