param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
if ($Version -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Version may contain only letters, numbers, dot, underscore, and hyphen."
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repoRoot "deployment\releases"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repoRoot "backend\.venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Create the project virtual environment and install backend test dependencies."
    }
    $python = $pythonCommand.Source
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python executable not found: $python"
}
if (-not (Get-Command "node.exe" -ErrorAction SilentlyContinue)) {
    throw "Node.js 22 is required to build the frontend."
}
$nodeVersion = (& node.exe --version)
if ($nodeVersion -notmatch '^v(22|24)\.') {
    throw "Node.js 22 or 24 is required; found $nodeVersion."
}
$frontend = Join-Path $repoRoot "frontend"
if (-not (Test-Path -LiteralPath (Join-Path $frontend "package-lock.json"))) {
    throw "frontend\package-lock.json is required for a reproducible release build."
}
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "backend\requirements.lock"))) {
    throw "backend\requirements.lock is required for a reproducible host installation."
}

Push-Location $repoRoot
try {
    & $python -m unittest discover -s backend\tests -v
    if ($LASTEXITCODE -ne 0) {
        throw "Backend tests failed; release was not created."
    }
    Push-Location $frontend
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend locked dependency installation failed."
        }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend production build failed; release was not created."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

$distIndex = Join-Path $frontend "dist\index.html"
if (-not (Test-Path -LiteralPath $distIndex -PathType Leaf)) {
    throw "The frontend build did not produce frontend\dist\index.html."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$archivePath = Join-Path $OutputDirectory "yathi-pdi-$Version.zip"
if (Test-Path -LiteralPath $archivePath) {
    throw "Release archive already exists; choose a new version."
}
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("pdi-release-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $backendTarget = Join-Path $stage "backend"
    New-Item -ItemType Directory -Path $backendTarget | Out-Null
    $backendSource = Join-Path $repoRoot "backend"
    & robocopy.exe $backendSource $backendTarget /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 `
        /XD ".venv" "venv" "__pycache__" ".pytest_cache" "logs" "generated_reports" "uploads" `
        /XF ".env" ".env.*" "*.db" "*.sqlite" "*.sqlite3" "*.pyc" "*.log" "*.pem" "*.key" "*.p12" "*.pfx" |
        Out-Host
    if ($LASTEXITCODE -ge 8) {
        throw "Could not stage backend application files (robocopy exit code $LASTEXITCODE)."
    }

    $frontendTarget = Join-Path $stage "frontend\dist"
    New-Item -ItemType Directory -Path $frontendTarget -Force | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $frontend "dist") -Force |
        Copy-Item -Destination $frontendTarget -Recurse -Force

    $deploymentTarget = Join-Path $stage "deployment\windows"
    New-Item -ItemType Directory -Path $deploymentTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $PSScriptRoot "*") -Destination $deploymentTarget -Recurse -Force

    $manifest = [ordered]@{
        version = $Version
        built_at_utc = [DateTime]::UtcNow.ToString("o")
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage "release.json") -Encoding UTF8

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stage,
        $archivePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    $zip = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $unsafeEntries = @(
            $zip.Entries | Where-Object {
                $_.FullName -match '(^|/)\.env($|\.)' -or
                $_.FullName -match '\.(db|sqlite|sqlite3|pem|key|p12|pfx)$' -or
                $_.FullName -match '(^|/)(uploads|generated_reports|backups)/'
            }
        )
        if ($unsafeEntries.Count -gt 0) {
            throw "Release contains data or secret-like files: $($unsafeEntries[0].FullName)."
        }
        if (-not ($zip.Entries.FullName -contains "frontend/dist/index.html")) {
            throw "Release archive is missing the built frontend."
        }
        if (-not ($zip.Entries.FullName -contains "backend/requirements.lock")) {
            throw "Release archive is missing locked backend dependencies."
        }
    }
    finally {
        $zip.Dispose()
    }

    Write-Output "Release created and validated: $archivePath"
    Write-Output "Transfer this ZIP to the company host; do not copy .env, database, upload, template, report, or backup files into it."
}
catch {
    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath -Force
    }
    throw
}
finally {
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}
