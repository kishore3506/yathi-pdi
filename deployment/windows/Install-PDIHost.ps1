param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseArchive
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
$archive = (Resolve-Path -LiteralPath $ReleaseArchive).Path
if (-not (Test-Path -LiteralPath $paths.ProgramRoot)) {
    New-Item -ItemType Directory -Path $paths.ProgramRoot -Force | Out-Null
}
if (Test-Path -LiteralPath $paths.CurrentRoot) {
    throw "An application is already installed. Use Update-PDI.ps1 instead of reinstalling."
}

$stage = Join-Path $paths.ProgramRoot ("install-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    foreach ($requiredPath in @(
        "release.json",
        "backend\requirements.lock",
        "frontend\dist\index.html",
        "deployment\windows\host.env.example"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $requiredPath))) {
            throw "Release archive is missing $requiredPath."
        }
    }

    $pathsToCreate = @(
        $paths.DataRoot,
        $paths.ConfigRoot,
        $paths.ToolsRoot,
        $paths.VenvRoot,
        $paths.DataFilesRoot,
        $paths.LogsRoot,
        $paths.BackupRoot,
        (Join-Path $paths.DataFilesRoot "Uploads"),
        (Join-Path $paths.DataFilesRoot "Templates"),
        (Join-Path $paths.DataFilesRoot "Reports"),
        $paths.IISRoot
    )
    foreach ($path in $pathsToCreate) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }

    $configSource = Join-Path $stage "deployment\windows\host.env.example"
    if (-not (Test-Path -LiteralPath $paths.ConfigFile)) {
        $configText = Get-Content -LiteralPath $configSource -Raw
        $secretBytes = New-Object byte[] 48
        $random = [Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $random.GetBytes($secretBytes)
        }
        finally {
            $random.Dispose()
        }
        $sessionSecret = [Convert]::ToBase64String($secretBytes)
        $configText = $configText.Replace(
            "SESSION_SECRET=__GENERATE_DURING_INSTALL__",
            "SESSION_SECRET=$sessionSecret"
        )
        Set-Content -LiteralPath $paths.ConfigFile -Value $configText -Encoding UTF8
    }

    $release = Get-Content -LiteralPath (Join-Path $stage "release.json") -Raw | ConvertFrom-Json
    if ([string]$release.version -notmatch '^[A-Za-z0-9._-]+$') {
        throw "The release manifest has an invalid version."
    }
    Move-Item -LiteralPath $stage -Destination $paths.CurrentRoot

    Get-ChildItem -LiteralPath (Join-Path $paths.CurrentRoot "deployment\windows") -Filter "*.ps1" |
        Copy-Item -Destination $paths.ToolsRoot -Force

    $pythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if (-not $pythonLauncher) {
        throw "Python Launcher was not found. Install Python 3.12 x64 for all users, then rerun this script."
    }
    $venvPath = Join-Path $paths.VenvRoot ([string]$release.version)
    if (-not (Test-Path -LiteralPath $venvPath)) {
        & $pythonLauncher.Source -3.12 -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the Python 3.12 virtual environment."
        }
    }
    $python = Get-PDIPythonPath -Version ([string]$release.version)
    & $python -m pip install --disable-pip-version-check -r (Join-Path $paths.CurrentRoot "backend\requirements.lock")
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }

    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
    & $icacls $paths.DataRoot /inheritance:r /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not restrict the PDI data folder ACL." }
    & $icacls $paths.DataRoot /grant:r `
        "SYSTEM:(OI)(CI)F" `
        "BUILTIN\Administrators:(OI)(CI)F" `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)M" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant the backend its data-folder permissions." }
    foreach ($restrictedPath in @($paths.ConfigRoot, $paths.ToolsRoot, $paths.VenvRoot)) {
        & $icacls $restrictedPath /inheritance:r | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not restrict permissions on $restrictedPath." }
    }
    & $icacls $paths.ConfigRoot /grant:r `
        "SYSTEM:(OI)(CI)F" `
        "BUILTIN\Administrators:(OI)(CI)F" `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)R" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set configuration-file permissions." }
    & $icacls $paths.ToolsRoot /grant:r `
        "SYSTEM:(OI)(CI)F" `
        "BUILTIN\Administrators:(OI)(CI)F" `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set host-tools permissions." }
    & $icacls $paths.VenvRoot /grant:r `
        "SYSTEM:(OI)(CI)F" `
        "BUILTIN\Administrators:(OI)(CI)F" `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set virtual-environment permissions." }
    & $icacls $paths.CurrentRoot /grant `
        "NT AUTHORITY\LOCAL SERVICE:(OI)(CI)RX" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant the backend access to application files." }

    Set-PDIProcessEnvironment -ReleaseRoot $paths.CurrentRoot
    Push-Location $paths.CurrentRoot
    try {
        & $python -m backend.storage_migration
        if ($LASTEXITCODE -ne 0) {
            throw "Initial database/template setup failed. See the PDI logs before retrying."
        }
    }
    finally {
        Pop-Location
    }

    Write-Output "PDI application installed at $($paths.CurrentRoot)."
    Write-Output "Persistent data and configuration are under $($paths.DataRoot)."
    Write-Output "Review $($paths.ConfigFile), create the first administrator, configure HTTPS, then register the scheduled task."
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
