param(
    [Parameter(Mandatory = $true)]
    [string]$CertificateThumbprint
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

$paths = Get-PDIPaths
Assert-PDIHostConfigReady
$values = Get-PDIConfigValues -Path $paths.ConfigFile
$origin = [Uri]$values["PUBLIC_APP_ORIGIN"]
$hostname = $origin.DnsSafeHost
$thumbprint = $CertificateThumbprint.Replace(" ", "").ToUpperInvariant()
if ($thumbprint -notmatch '^[A-F0-9]{40,64}$') {
    throw "Enter the certificate thumbprint from the Local Computer\Personal store."
}

$certificate = Get-ChildItem -LiteralPath Cert:\LocalMachine\My |
    Where-Object { $_.Thumbprint -eq $thumbprint } |
    Select-Object -First 1
if (-not $certificate) {
    throw "Certificate $thumbprint was not found in Local Computer\Personal."
}
if (-not $certificate.HasPrivateKey -or $certificate.NotAfter -le (Get-Date)) {
    throw "The selected server certificate must be unexpired and include its private key."
}
$dnsNames = @($certificate.DnsNameList | ForEach-Object { $_.Unicode })
$hostMatches = $dnsNames -contains $hostname
foreach ($dnsName in $dnsNames) {
    if (-not $dnsName.StartsWith("*.", [StringComparison]::Ordinal)) {
        continue
    }
    $suffix = $dnsName.Substring(1)
    if (
        $hostname.EndsWith($suffix, [StringComparison]::OrdinalIgnoreCase) -and
        ($hostname.Split(".").Count -eq ($suffix.TrimStart(".").Split(".").Count + 1))
    ) {
        $hostMatches = $true
    }
}
if (-not $hostMatches) {
    throw "The certificate SAN does not include $hostname. Do not bypass browser certificate warnings."
}

Import-Module WebAdministration -ErrorAction Stop
$siteName = "YathiPumps-PDI"
$poolName = "YathiPumps-PDI"
if (-not (Get-Command New-Website -ErrorAction SilentlyContinue)) {
    throw "IIS management tools are unavailable. Enable IIS Management Scripts and Tools first."
}
if (-not (Get-WebGlobalModule -Name "RewriteModule" -ErrorAction SilentlyContinue)) {
    throw "IIS URL Rewrite is missing. Install the Microsoft IIS URL Rewrite module first."
}

$appcmd = Join-Path $env:SystemRoot "System32\inetsrv\appcmd.exe"
if (-not (Test-Path -LiteralPath $appcmd)) {
    throw "IIS is not installed. Enable IIS before configuring the reverse proxy."
}

if (-not (Test-Path "IIS:\AppPools\$poolName")) {
    New-WebAppPool -Name $poolName | Out-Null
}
Set-ItemProperty "IIS:\AppPools\$poolName" -Name managedRuntimeVersion -Value ""
Set-ItemProperty "IIS:\AppPools\$poolName" -Name startMode -Value "AlwaysRunning"
Set-ItemProperty "IIS:\AppPools\$poolName" -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)

if (-not (Test-Path "IIS:\Sites\$siteName")) {
    New-Website `
        -Name $siteName `
        -PhysicalPath $paths.IISRoot `
        -ApplicationPool $poolName `
        -Port 443 `
        -HostHeader $hostname `
        -Ssl | Out-Null
}
else {
    $site = Get-Website -Name $siteName
    if ($site.PhysicalPath -ne $paths.IISRoot) {
        throw "The existing $siteName site has an unexpected physical path; refusing to replace it."
    }
}

$siteBindingFilter = "system.applicationHost/sites/site[@name='$siteName']/bindings"
$httpsBinding = Get-WebBinding -Name $siteName -Protocol https -ErrorAction SilentlyContinue
if (-not $httpsBinding) {
    Add-WebConfigurationProperty `
        -PSPath "MACHINE/WEBROOT/APPHOST" `
        -Filter $siteBindingFilter `
        -Name "." `
        -Value @{
            protocol = "https"
            bindingInformation = "*:443:$hostname"
            sslFlags = 1
        }
}
else {
    Set-WebConfigurationProperty `
        -PSPath "MACHINE/WEBROOT/APPHOST" `
        -Filter "$siteBindingFilter/binding[@protocol='https']" `
        -Name sslFlags `
        -Value 1
}
$httpsBinding = Get-WebBinding -Name $siteName -Protocol https
if ($httpsBinding.bindingInformation -notlike "*:443:$hostname") {
    throw "The existing IIS HTTPS binding does not match $hostname on port 443."
}
$httpsBinding.AddSslCertificate($thumbprint, "My")

$webConfig = @'
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <httpErrors existingResponse="PassThrough" />
    <rewrite>
      <rules>
        <rule name="YathiPumps PDI backend reverse proxy" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8765/{R:1}" appendQueryString="true" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
'@
Set-Content -LiteralPath (Join-Path $paths.IISRoot "web.config") -Value $webConfig -Encoding UTF8

& $appcmd set config -section:system.webServer/proxy /enabled:true /preserveHostHeader:true /timeout:"00:03:00" /commit:apphost
if ($LASTEXITCODE -ne 0) {
    throw "Could not enable IIS Application Request Routing proxy. Confirm ARR is installed."
}

$icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
& $icacls $paths.IISRoot /grant "IIS_IUSRS:(OI)(CI)RX" /T /C | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not grant IIS access to its proxy configuration." }

Start-WebAppPool -Name $poolName
Start-Website -Name $siteName
Write-Output "IIS is configured to proxy https://$hostname/ to the loopback-only PDI backend."
Write-Output "Employee browsers must trust the issuing company CA; certificate renewal must update this IIS binding."
