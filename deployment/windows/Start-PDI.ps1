$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PDIPaths
$manifestPath = Join-Path $paths.CurrentRoot "release.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "PDI release manifest is missing: $manifestPath"
}
$expectedVersion = [string](Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).version
$task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    throw "Scheduled task '$($paths.TaskName)' is not installed. Run Register-PDITask.ps1 as administrator."
}
if ($task.State -ne "Running") {
    Start-ScheduledTask -TaskName $paths.TaskName
}

$deadline = (Get-Date).AddSeconds(90)
do {
    Start-Sleep -Seconds 2
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8765/api/health" `
            -UseBasicParsing `
            -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $version = Invoke-RestMethod `
                -Uri "http://127.0.0.1:8765/api/version" `
                -TimeoutSec 3
            if ($version.version -eq $expectedVersion) {
                Write-Output "PDI release $expectedVersion is healthy on loopback port 8765."
                exit 0
            }
        }
    }
    catch {
        $task = Get-ScheduledTask -TaskName $paths.TaskName
        if ($task.State -ne "Running" -and (Get-Date) -ge $deadline) {
            throw "PDI backend task did not start. Check Task Scheduler history and $($paths.LogsRoot)\pdi.log."
        }
    }
} while ((Get-Date) -lt $deadline)

throw "PDI backend did not become healthy within 90 seconds. Check Task Scheduler history and $($paths.LogsRoot)\pdi.log."
