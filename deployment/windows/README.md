# Windows LAN deployment

This guide hosts one shared PDI application on an always-on company Windows computer. FastAPI serves the built Vite PWA and `/api`; IIS provides the employee-facing HTTPS origin and proxies to FastAPI on loopback. SQLite and all business files live under `C:\ProgramData\Yathi Pumps PDI`, separate from replaceable application releases under `C:\Program Files\Yathi Pumps PDI`.

No public cloud, tunnel, router port-forwarding, or development terminal is required. The Windows host must stay powered on and awake. This design is for one host, one FastAPI process, and low-to-moderate office concurrency; it is not highly available.

## What is in this repository

- React frontend built with Vite; its API calls are relative to `/api`.
- Python FastAPI backend serves `frontend/dist` and the API from one origin.
- SQLite database, Excel templates and generated Excel/PDF files.
- Gemini document extraction remains on the backend; employees must review extracted purchase-order details before generating reports.
- Optional n8n email integration. There is no importable n8n workflow in this repository; see [`n8n/README.md`](../../n8n/README.md) to create and operate a company-owned workflow.
- Cloud-side printing is not used. Employees download/open the PDF and print from their own device.
- Existing login, employee roles, update controls, relative API requests, PWA shell, and report behavior are retained.
- Windows scripts, portable backup, and file-reference migration are under this folder.

## Prerequisites and company IT work

Ask company IT to complete these before inviting employees:

1. Choose a stable, always-on Windows 10/11 Pro or Windows Server computer with adequate disk space and a supported power supply. Keep its system clock synchronized. Reserve its LAN address in DHCP; do not rely on a manually guessed or changing address.
2. Provide an internal DNS name, for example `pdi.company.example`, resolving to that reserved address on the employee network. Android phones must use company Wi-Fi and be able to resolve and reach this host; guest Wi-Fi client isolation will prevent access.
3. Provide a server-authentication TLS certificate for that DNS name, including its private key, installed in **Local Computer → Personal**. Prefer the company internal CA. The certificate SAN must match the name employees use. Distribute the issuing root/intermediate CA trust to managed Windows browsers and Android devices (Group Policy and the company device-management/MDM process). Do not ask employees to bypass a browser warning.
4. Arrange certificate renewal. With company CA auto-enrollment, confirm renewal and rebind IIS if the certificate thumbprint changes. If renewal is manual, schedule a reminder before expiry and rerun `Configure-IISProxy.ps1` with the renewed certificate thumbprint.
5. Confirm the office subnet and Windows network profile (`Domain` for a domain-authenticated corporate network, or `Private` if IT intentionally configures it that way). Do not use the `Public` profile. The firewall script opens only TCP 443 from the supplied office subnet and explicitly blocks inbound TCP 8765.
6. Confirm the host can make outbound HTTPS connections to Gemini and any approved n8n/email service. No incoming public internet or router port-forward is needed.
7. Approve access to the Gemini API key and, only if email is being enabled, the company-owned sender mailbox/n8n credentials. Never paste secrets into chat or put them in the release ZIP.

The preferred HTTPS approach is IIS with Microsoft's URL Rewrite and Application Request Routing (ARR) modules, using a certificate issued by the company's trusted CA. IIS listens on HTTPS 443; FastAPI is explicitly bound to `127.0.0.1:8765`. This is a practical Windows-native reverse proxy, but the certificate and CA trust are company IT responsibilities. Internal DNS alone does not make a certificate trusted.

Microsoft references: [IIS URL Rewrite](https://www.iis.net/downloads/microsoft/url-rewrite), [IIS Application Request Routing](https://www.iis.net/downloads/microsoft/application-request-routing), [Microsoft Learn reverse-proxy walkthrough](https://learn.microsoft.com/en-us/iis/extensions/url-rewrite-module/reverse-proxy-with-url-rewrite-v2-and-application-request-routing), and [Task Scheduler command reference](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create). Confirm the Windows/IIS versions and current module installers with IT before installing.

## 1. Build a release on the development computer

Install Python 3.12 and Node.js 22 (the version pinned in `frontend/.nvmrc`) or Node.js 24 on the development computer. From the repository root in PowerShell, assign a new release version each time:

```powershell
.\deployment\windows\Build-Release.ps1 -Version "2026.06.04.1"
```

The script runs the backend `unittest` suite, runs `npm ci` and `npm run build`, and creates a validated ZIP under `deployment\releases`. It builds the frontend from source. It excludes environment files, databases, uploads, generated reports, backups, and private keys. Do not copy any of those files into the ZIP.

Transfer only the ZIP to the company host using an approved company file share or removable media. The host needs Python 3.12 x64 and internet access to install the locked Python packages; it does not need Node.js, npm, VS Code, or a frontend development server.

## 2. Install IIS and reverse-proxy prerequisites

In an elevated PowerShell window on the host, enable IIS and its management tools (a Windows restart may be required):

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName IIS-WebServerRole,IIS-WebServer,IIS-CommonHttpFeatures,IIS-HttpErrors,IIS-StaticContent,IIS-DefaultDocument,IIS-HttpLogging,IIS-RequestFiltering,IIS-ManagementConsole,IIS-ManagementScriptingTools -All
```

Install the Microsoft IIS **URL Rewrite** and **Application Request Routing (ARR)** modules from their official Microsoft IIS download/documentation pages. The script does not download installers or change other IIS sites. Confirm the company certificate is in `Cert:\LocalMachine\My` with a private key and the right SAN:

```powershell
Get-ChildItem Cert:\LocalMachine\My |
  Select-Object Subject, Thumbprint, NotAfter, HasPrivateKey, DnsNameList
```

The reverse-proxy setup script will refuse an absent, expired, private-key-less, or hostname-mismatched certificate. It will also stop if URL Rewrite or ARR is missing.

## 3. Install the PDI release and configure secrets

Open an elevated PowerShell window. Replace the example paths with the actual transfer location and release version:

```powershell
Expand-Archive -LiteralPath "C:\Transfer\yathi-pdi-2026.06.04.1.zip" -DestinationPath "C:\Transfer\PDI-Release"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Transfer\PDI-Release\deployment\windows\Install-PDIHost.ps1" -ReleaseArchive "C:\Transfer\yathi-pdi-2026.06.04.1.zip"
```

The installer puts replaceable application code in `C:\Program Files\Yathi Pumps PDI\current`, creates a Python virtual environment per release, and creates persistent data/configuration under `C:\ProgramData\Yathi Pumps PDI`. It creates `.env` only if no configuration file exists; later updates preserve it. It does not import, reset, or overwrite business data or registered templates.

Edit the host-only configuration as an administrator:

```powershell
notepad.exe "$env:ProgramData\Yathi Pumps PDI\config\.env"
```

Set at least:

```text
PUBLIC_APP_ORIGIN=https://pdi.company.example
GEMINI_API_KEY=<company-managed Gemini key>
GEMINI_MODEL=gemini-3.5-flash-lite
```

Keep the installer-generated `SESSION_SECRET`; do not share it. The installer restricts configuration so `Local Service` can read it but regular Windows users cannot. Set `N8N_WEBHOOK_URL`, `N8N_WEBHOOK_TOKEN`, and `N8N_FROM_EMAIL` only after the company n8n workflow is secured and tested. Keep email variables blank for initial installation/testing. Do not add credentials to React, Vite, `frontend/dist`, PowerShell command arguments, or the release archive.

The settings file also gives separate persistent paths for the database, uploads, registered templates, generated reports, logs, and backups. You can review these paths but should not move or rename them without stopping the task and updating configuration.

## 4. Create the first administrator and migrate existing data (optional)

Run initial administrator setup in an interactive PowerShell window so the password is entered through hidden prompts:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Create-Admin.ps1"
```

Use a unique work account and a strong password of at least 12 characters. No default administrator or password is installed. Create inspector, approver, and other administrator accounts after sign-in; API routes enforce roles.

To migrate the current local app's records, first create a portable backup on the development computer. From the repository root, with the local environment configured:

```powershell
backend\.venv\Scripts\python.exe -m backend.backup_cli backup --destination "C:\Transfer\pdi-business-data.zip"
```

This archive contains sensitive business data, uploaded documents, registered templates, reports, and employee password hashes. Store and transfer it only using an approved protected channel. Do not email it or commit it. Create the host administrator first, then import the archive before normal production use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Restore-InitialBackup.ps1" -BackupArchive "C:\Transfer\pdi-business-data.zip"
```

The import is intentionally restricted to a newly initialized destination with no business records. It preserves the host administrator, migrates referenced files to the persistent directories, and refuses to replace existing business records. Do not copy a live SQLite database with Explorer or run an import against a populated host.

## 5. Configure HTTPS, start-at-boot, and firewall

Configure IIS to listen on the internal hostname using the certificate thumbprint from the prior step:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Configure-IISProxy.ps1" -CertificateThumbprint "PASTE_CERTIFICATE_THUMBPRINT"
```

The IIS site proxies the same HTTPS origin to `127.0.0.1:8765`; it does not serve a separate frontend or expose the FastAPI port. The backend sets secure session cookies in production and validates the configured public origin.

Register the Windows scheduled task from elevated PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Register-PDITask.ps1"
```

The task is named `YathiPumps-PDI-Backend`, runs as `NT AUTHORITY\LOCAL SERVICE` whether anyone is logged in or not, starts at boot, ignores duplicate starts, retries unexpected failures, and has no execution time limit. No employee or administrator password is stored in the script or task.

Open the HTTPS port only to the actual office subnet. Replace the example subnet and choose the IT-confirmed profile:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Set-OfficeFirewall.ps1" -OfficeSubnet "192.168.10.0/24" -Profile Domain
```

Use `-Profile Private` only if IT has intentionally configured the office network as Private. The reverse proxy is the employee-facing listener. The task runner detects an occupied backend port and logs a safe startup error. Do not create a router port-forward or expose port 8765.

Start and verify the backend:

```powershell
& "$env:ProgramData\Yathi Pumps PDI\tools\Start-PDI.ps1"
& "$env:ProgramData\Yathi Pumps PDI\tools\Status-PDI.ps1"
Invoke-RestMethod "https://pdi.company.example/api/version"
```

The first command waits for the loopback health endpoint. Check the HTTPS URL from a second office computer and an Android phone on company Wi-Fi. Do not bypass certificate warnings. A plain `http://<LAN-IP>` address is not a production PWA URL; this design intentionally keeps FastAPI on loopback.

Useful task commands (run in PowerShell):

```powershell
Get-ScheduledTask -TaskName "YathiPumps-PDI-Backend"
Get-ScheduledTaskInfo -TaskName "YathiPumps-PDI-Backend"
Stop-ScheduledTask -TaskName "YathiPumps-PDI-Backend"
Start-ScheduledTask -TaskName "YathiPumps-PDI-Backend"
```

To remove only the scheduled task (not the application or business data), run elevated:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Remove-PDITask.ps1"
```

For uptime, open Windows **Settings → System → Power & battery → Screen and sleep** and set the plugged-in sleep option to **Never**, according to company policy. This is a deliberate IT/operator decision; the installer does not change power settings. The display can turn off while the computer remains awake.

## 6. Install the PWA

- **Android:** on company Wi-Fi, open `https://pdi.company.example` in Chrome and choose **Install app** or **Add to Home screen**.
- **Windows:** open the HTTPS URL in Chrome or Edge and use the address-bar install icon or browser menu → **Install this site as an app**.

Employees must trust the company CA on their devices. The app caches only the generic static application shell/assets. It does not cache purchase orders, API responses, authenticated business data, or reports. Gemini extraction, saving, approval, report generation, and downloads require a connection to the host and internet access for Gemini. Offline report generation is not supported.

On release, connected apps detect a new frontend and show **“Update available. Save your work and reload.”** Users apply it themselves. Unsaved inspection edits prevent applying the update. Closed/offline devices check when they reconnect. The update script carries forward prior hashed static assets so already-open sessions can finish loading; this uses some additional disk space. Code deployment does not synchronize records between separate databases—the host's persistent database is the shared source of truth.

## 7. Backups and restore

Create a consistent SQLite and file backup from an elevated PowerShell window:

```powershell
& "$env:ProgramData\Yathi Pumps PDI\tools\Backup-PDI.ps1"
```

The script briefly stops the scheduled backend if it is running, takes a consistent SQLite snapshot, includes the referenced upload/template/report files, and restarts the task if it was previously running. Copy the resulting ZIP from `C:\ProgramData\Yathi Pumps PDI\Backups` to a separate, approved encrypted destination (for example, an access-controlled company backup share). A backup only on the host disk does **not** protect against disk failure, theft, ransomware, or loss of the host.

Backups contain confidential documents, records, and password hashes. Restrict access and retention. Periodically test restoration on a separate fresh installation. `Restore-InitialBackup.ps1` refuses to overwrite a populated database; it is for initial restore to a new/empty environment. Do not manually replace the live SQLite database while the app is running. Coordinate recovery if the host fails; restoring a backup loses changes made after that backup.

## 8. Publish the next update and roll back

Daily workflow:

1. Edit on the development computer.
2. Run the tests and `Build-Release.ps1` with a new version.
3. Review the build result and transfer the release ZIP to the host. Uncommitted local changes are not pushed or deployed by this workflow.
4. On the host, run the update script elevated:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Update-PDI.ps1" -ReleaseArchive "C:\Transfer\yathi-pdi-2026.06.05.1.zip"
   ```

5. The script installs dependencies into a release-specific virtual environment, stops the scheduled task, creates a pre-update business-data backup, switches application code without touching ProgramData, starts the backend, and verifies the local health endpoint. Storage migrations run before serving. It retains the previous code and previous hashed assets.
6. Verify `https://pdi.company.example/api/health`, `/api/version`, login, a safe test upload/report flow, and expected data. Do not send customer email during checks. Users then apply the PWA update after saving.

To roll back application code to the most recently retained release, run elevated:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\Yathi Pumps PDI\tools\Rollback-PDI.ps1"
```

Or specify a particular retained directory under `C:\Program Files\Yathi Pumps PDI\rollback`. The script makes a pre-rollback backup and health-checks the previous code. A code rollback does **not** reverse database migrations or discard later business records. Database changes must remain compatible with the intended rollback release; restoring an older database snapshot is a separate recovery decision and can lose later writes.

## 9. Email, printing, monitoring, and troubleshooting

- **n8n:** it must be n8n Cloud or an independently running company service reachable by the PDI host. An n8n process in VS Code or on an employee laptop is not reliable. If company-hosted, IT must install it as a Windows service or scheduled task with start-at-boot and restart-on-failure settings, plus persistent n8n configuration and secured credentials; this repository does not install or supervise n8n. Configure the company sender credentials in n8n's credential store, set the PDI `N8N_*` values only after the workflow is secured, and respond HTTP 200 only after the email node succeeds. Use only internal test recipients. See [`n8n/README.md`](../../n8n/README.md). If an internal TLS certificate is used by n8n, its CA must be trusted by Python `requests`; never disable certificate verification.
- **Printing:** the scheduled backend does not shell-print and does not run in an interactive desktop. Download/open the PDF and print with the employee computer/phone's available options. Opening/downloading a PDF is not proof of a physical print; no physical-print success is claimed.
- **Health/version:** from host, use `Status-PDI.ps1`; from a trusted employee device, open `/api/health` and `/api/version` on the HTTPS hostname.
- **Logs:** backend logs rotate under `C:\ProgramData\Yathi Pumps PDI\Logs\pdi.log`; launcher errors rotate in `startup.log`. They avoid request/document contents and secrets. Task Scheduler history is also useful.
- **Port occupied:** inspect with `Get-NetTCPConnection -State Listen -LocalPort 8765`; identify and resolve the conflicting service rather than changing the PDI port casually.
- **Task failure:** inspect `Get-ScheduledTaskInfo -TaskName "YathiPumps-PDI-Backend"`, Task Scheduler **History**, and the logs. Confirm configuration, Python environment, folder permissions, and outbound network.
- **HTTPS warning:** stop; do not bypass it. Ask IT to verify the hostname, certificate SAN/expiry/private key, IIS binding, DNS, and employee-device CA trust.
- **No phone access:** confirm office Wi-Fi (not guest), DNS resolution, DHCP reservation, office-subnet firewall rule/profile, and that TCP 443 is reachable. Do not enable public forwarding.
- **Computer sleep:** confirm the host remains awake while plugged in. The application is unavailable during sleep, power loss, network outage, host failure, Windows updates/restarts, or maintenance.

## Acceptance checklist

Mark each item only after testing on the real company setup:

- [ ] Restart the host computer.
- [ ] Do not open VS Code; verify Task Scheduler starts the backend.
- [ ] Connect from another company computer using the trusted HTTPS hostname.
- [ ] Connect from an Android phone on company Wi-Fi and install/open the PWA.
- [ ] Switch off the development laptop; verify shared use continues.
- [ ] Verify login and inspector/approver/administrator authorization.
- [ ] Verify upload, Gemini extraction, review/correction, report generation, and Excel/PDF downloads.
- [ ] Verify a release update notification, unsaved-work guard, and safe user-applied update.
- [ ] Verify records, uploaded files, registered templates, and reports remain after host restart and code update.
- [ ] Create a backup, copy it off-host, and test restore on a separate fresh installation.
- [ ] Verify email only with a company-controlled test recipient; no customer email during setup.
- [ ] Verify employees print a downloaded PDF using their own device; do not infer physical printing from an app status.

## Operating limits and costs

- The Windows host must remain switched on, awake, connected to the office network, and maintained. Host failure, power loss, sleep, or network failure makes the shared app unavailable.
- Employees must reach the host over the company network. The host needs internet for Gemini and external email/n8n services.
- SQLite is suitable for a small single-host deployment with modest write concurrency. The app uses one backend process; do not run multiple workers or replicas. Heavy simultaneous writes may queue or return conflicts. If concurrency or availability requirements grow, plan a database migration to PostgreSQL and shared storage.
- There are no hosting subscription fees in this on-prem design. Electricity, existing hardware/network, Windows licensing/IT support, company PKI/domain infrastructure, any Gemini API usage, and any n8n/email services may still incur costs.
- No installation, certificate issuance, DHCP/DNS configuration, firewall change, employee-device trust, reboot test, Android test, physical print, or backup-restore test is claimed complete until performed on the company host/network.
