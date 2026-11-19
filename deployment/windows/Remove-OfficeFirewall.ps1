$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
Assert-PDIAdministrator

Remove-NetFirewallRule -DisplayName "Yathi Pumps PDI HTTPS (Office LAN)" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Yathi Pumps PDI Backend Loopback Only" -ErrorAction SilentlyContinue
Write-Output "PDI-specific firewall rules removed. This does not uninstall IIS or the application."
