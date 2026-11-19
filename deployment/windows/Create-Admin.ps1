$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$manifest = Get-Content -LiteralPath (Join-Path $paths.CurrentRoot "release.json") -Raw | ConvertFrom-Json
Set-PDIProcessEnvironment -ReleaseRoot $paths.CurrentRoot
$python = Get-PDIPythonPath -Version ([string]$manifest.version)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment is missing for release $($manifest.version)."
}

$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
$wasRunning = $task -and $task.State -eq "Running"
$wasRunning = Stop-PDITaskAndWait

$result = 1
try {
    Push-Location $paths.CurrentRoot
    try {
        & $python -m backend.create_admin
        $result = $LASTEXITCODE
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
            throw "Administrator command ended, but the backend did not restart successfully."
        }
    }
}
if ($result -ne 0) {
    throw "Administrator setup failed with exit code $result."
}
