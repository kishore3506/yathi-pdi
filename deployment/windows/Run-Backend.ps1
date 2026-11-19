$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

try {
    $paths = Get-PDIPaths
    Assert-PDIHostConfigReady
    if (-not (Test-Path -LiteralPath $paths.CurrentRoot -PathType Container)) {
        throw "PDI application files are missing: $($paths.CurrentRoot)"
    }

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $processes = @(
            $listeners |
                Select-Object -ExpandProperty OwningProcess -Unique |
                ForEach-Object {
                    $process = Get-Process -Id $_ -ErrorAction SilentlyContinue
                    if ($process) { "$($process.ProcessName) (PID $_)" } else { "PID $_" }
                }
        ) -join ", "
        throw "Loopback port 8765 is already occupied by $processes. Stop the conflicting service before starting PDI."
    }

    $manifest = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
    Set-PDIProcessEnvironment -ReleaseRoot $paths.CurrentRoot
    $python = Get-PDIPythonPath -Version ([string]$manifest.version)
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Python environment is missing for release $($manifest.version)."
    }
}
catch {
    Write-PDIRotatingLog -Message ("Backend startup validation failed (" + $_.Exception.GetType().FullName + ").")
    throw
}

Push-Location $paths.CurrentRoot
try {
    & $python -m backend.windows_server
    $backendExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($backendExitCode -eq 0) {
    Write-PDIRotatingLog -Message "Backend exited unexpectedly with code 0."
    [Console]::Error.WriteLine("The backend exited unexpectedly with code 0; reporting failure so Task Scheduler can restart it.")
    exit 1
}
Write-PDIRotatingLog -Message "Backend exited with code $backendExitCode."
exit $backendExitCode
