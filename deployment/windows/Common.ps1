function Get-PDIPaths {
    $programRoot = Join-Path $env:ProgramFiles "Yathi Pumps PDI"
    $dataRoot = Join-Path $env:ProgramData "Yathi Pumps PDI"
    [pscustomobject]@{
        TaskName = "YathiPumps-PDI-Backend"
        ProgramRoot = $programRoot
        CurrentRoot = Join-Path $programRoot "current"
        RollbackRoot = Join-Path $programRoot "rollback"
        DataRoot = $dataRoot
        ConfigRoot = Join-Path $dataRoot "config"
        ConfigFile = Join-Path (Join-Path $dataRoot "config") ".env"
        ToolsRoot = Join-Path $dataRoot "tools"
        VenvRoot = Join-Path $dataRoot "venvs"
        DataFilesRoot = Join-Path $dataRoot "Data"
        LogsRoot = Join-Path $dataRoot "Logs"
        BackupRoot = Join-Path $dataRoot "Backups"
        IISRoot = Join-Path $dataRoot "IIS"
    }
}

function Test-PDIAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-PDIAdministrator {
    if (-not (Test-PDIAdministrator)) {
        throw "Run this script from an elevated PowerShell window (Run as administrator)."
    }
}

function Get-PDIConfigValues {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "PDI configuration file is missing: $Path"
    }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed.StartsWith("export ")) {
            $trimmed = $trimmed.Substring(7).Trim()
        }
        $separator = $trimmed.IndexOf("=")
        if ($separator -lt 1) {
            continue
        }
        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim().Trim('"').Trim("'")
        $values[$key] = $value
    }
    return $values
}

function Assert-PDIHostConfigReady {
    $paths = Get-PDIPaths
    $values = Get-PDIConfigValues -Path $paths.ConfigFile
    $secret = [string]$values["SESSION_SECRET"]
    if ($secret.Length -lt 32 -or $secret -eq "__GENERATE_DURING_INSTALL__") {
        throw "SESSION_SECRET is missing or too short in $($paths.ConfigFile)."
    }

    $origin = [string]$values["PUBLIC_APP_ORIGIN"]
    $uri = $null
    if (
        -not [Uri]::TryCreate($origin, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne "https" -or
        -not $uri.IsDefaultPort -or
        $uri.AbsolutePath -notin @("", "/") -or
        $uri.Query -or
        $uri.Fragment -or
        $uri.Host -match "replace-with"
    ) {
        throw "Set PUBLIC_APP_ORIGIN to the company HTTPS hostname before registering the task."
    }
    $ipAddress = $null
    if ([System.Net.IPAddress]::TryParse($uri.Host, [ref]$ipAddress)) {
        throw "PUBLIC_APP_ORIGIN must use the stable internal DNS hostname, not a LAN IP address."
    }
    $geminiKey = [string]$values["GEMINI_API_KEY"]
    if (-not $geminiKey -or $geminiKey -match "^replace-with") {
        throw "Set GEMINI_API_KEY in $($paths.ConfigFile) before starting the production backend."
    }
}

function Set-PDIProcessEnvironment {
    param([Parameter(Mandatory = $true)][string]$ReleaseRoot)
    $paths = Get-PDIPaths
    $manifestPath = Join-Path $ReleaseRoot "release.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Release manifest is missing: $manifestPath"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.version -notmatch '^[A-Za-z0-9._-]+$') {
        throw "The release manifest has an invalid version."
    }
    $env:PDI_ENV_FILE = $paths.ConfigFile
    $env:APP_ENV = "production"
    $env:APP_VERSION = [string]$manifest.version
    $env:HOST = "127.0.0.1"
    $env:PORT = "8765"
}

function Get-PDIPythonPath {
    param([Parameter(Mandatory = $true)][string]$Version)
    if ($Version -notmatch '^[A-Za-z0-9._-]+$') {
        throw "Invalid release version."
    }
    $paths = Get-PDIPaths
    return Join-Path (Join-Path (Join-Path $paths.VenvRoot $Version) "Scripts") "python.exe"
}

function Write-PDIRotatingLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $paths = Get-PDIPaths
    New-Item -ItemType Directory -Path $paths.LogsRoot -Force | Out-Null
    $config = @{}
    if (Test-Path -LiteralPath $paths.ConfigFile) {
        $config = Get-PDIConfigValues -Path $paths.ConfigFile
    }
    $maxBytes = 10MB
    $backupCount = 10
    if ([int64]::TryParse([string]$config["PDI_LOG_MAX_BYTES"], [ref]$maxBytes) -eq $false) {
        $maxBytes = 10MB
    }
    if ([int]::TryParse([string]$config["PDI_LOG_BACKUP_COUNT"], [ref]$backupCount) -eq $false) {
        $backupCount = 10
    }
    if ($maxBytes -lt 1024) { $maxBytes = 10MB }
    $backupCount = [Math]::Max(1, [Math]::Min(20, $backupCount))
    $logPath = Join-Path $paths.LogsRoot "startup.log"
    if ((Test-Path -LiteralPath $logPath) -and (Get-Item -LiteralPath $logPath).Length -ge $maxBytes) {
        $lastBackup = "$logPath.$backupCount"
        if (Test-Path -LiteralPath $lastBackup) {
            Remove-Item -LiteralPath $lastBackup -Force
        }
        for ($index = $backupCount - 1; $index -ge 1; $index--) {
            $source = "$logPath.$index"
            $destination = "$logPath." + ($index + 1)
            if (Test-Path -LiteralPath $destination) {
                Remove-Item -LiteralPath $destination -Force
            }
            if (Test-Path -LiteralPath $source) {
                Move-Item -LiteralPath $source -Destination $destination
            }
        }
        Move-Item -LiteralPath $logPath -Destination "$logPath.1"
    }
    Add-Content -LiteralPath $logPath `
        -Value ("{0:o} ERROR {1}" -f [DateTime]::Now, $Message) `
        -Encoding UTF8
}

function Stop-PDITaskAndWait {
    param([int]$TimeoutSeconds = 30)
    $paths = Get-PDIPaths
    $task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
    $wasRunning = $task -and $task.State -eq "Running"
    if ($wasRunning) {
        Stop-ScheduledTask -TaskName $paths.TaskName
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Start-Sleep -Seconds 1
        $task = Get-ScheduledTask -TaskName $paths.TaskName -ErrorAction SilentlyContinue
        $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)
    } while (
        (($task -and $task.State -eq "Running") -or $listeners.Count -gt 0) -and
        (Get-Date) -lt $deadline
    )
    if ($task -and $task.State -eq "Running") {
        throw "The PDI scheduled task did not stop within $TimeoutSeconds seconds."
    }
    if ($listeners.Count -gt 0) {
        $owners = @(
            $listeners |
                Select-Object -ExpandProperty OwningProcess -Unique |
                ForEach-Object {
                    $process = Get-Process -Id $_ -ErrorAction SilentlyContinue
                    if ($process) { "$($process.ProcessName) (PID $_)" } else { "PID $_" }
                }
        ) -join ", "
        throw "Loopback port 8765 is still occupied by $owners; no PDI maintenance action was performed."
    }
    return [bool]$wasRunning
}
