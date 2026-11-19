param(
    [Parameter(Mandatory = $true)]
    [string]$OfficeSubnet,
    [ValidateSet("Domain", "Private")]
    [string]$Profile = "Domain"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

if ($OfficeSubnet -notmatch '^(\d{1,3}\.){3}\d{1,3}/(?:[1-9]|[12]\d|3[0-2])$') {
    throw "Enter the office IPv4 subnet in CIDR form, for example 192.168.10.0/24."
}
$address = $OfficeSubnet.Split("/")[0]
foreach ($octet in $address.Split(".")) {
    if ([int]$octet -gt 255) {
        throw "The office subnet contains an invalid IPv4 address."
    }
}

$httpsRule = "Yathi Pumps PDI HTTPS (Office LAN)"
$backendRule = "Yathi Pumps PDI Backend Loopback Only"
Remove-NetFirewallRule -DisplayName $httpsRule -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName $backendRule -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName $httpsRule `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 443 `
    -RemoteAddress $OfficeSubnet `
    -Profile $Profile `
    -Description "Allows employee access to the PDI IIS HTTPS reverse proxy from the office subnet only." |
    Out-Null
New-NetFirewallRule `
    -DisplayName $backendRule `
    -Direction Inbound `
    -Action Block `
    -Protocol TCP `
    -LocalPort 8765 `
    -Profile Any `
    -Description "Prevents network access to the loopback-only PDI backend port." |
    Out-Null

Write-Output "Firewall configured: TCP 443 allowed only from $OfficeSubnet on the $Profile profile."
Write-Output "TCP 8765 is explicitly blocked for inbound connections; IIS proxies to 127.0.0.1."
