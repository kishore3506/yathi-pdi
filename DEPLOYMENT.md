# Production deployment and operations

## Architecture and limits

The application is deployed as one Docker web service on [Render](https://render.com/). Render builds the Vite frontend from source, packages it with FastAPI, and serves both the PWA and `/api` from the same HTTPS origin. A Render persistent SSD mounted at `/var/data` holds the SQLite database, uploaded purchase orders, generated reports, and user-uploaded templates. The laptop is not part of the production runtime.

Render is a good fit for this small initial deployment because its Git-linked Docker services, Blueprint configuration, HTTPS, health checks, and persistent disks cover the existing stack without adding another frontend host or an API gateway. The checked-in [`render.yaml`](./render.yaml) selects Singapore, one 1-vCPU/2-GB service, one worker, a 10-GB persistent disk, and deploys a linked `main` branch only after GitHub CI checks pass.

This first production topology intentionally retains SQLite because the existing backend uses SQLite directly throughout its routes and services. It is suitable only for modest write concurrency on **one application instance and one worker**. WAL, a 30-second busy timeout, full synchronous writes, and report revision checks are enabled. The revision check returns HTTP 409 instead of silently replacing an inspection changed by another employee. SQLite and this disk-backed deployment are not horizontally scalable or highly available; Render disks are attached to one instance, and deploys have a short interruption. Move the database to managed PostgreSQL and use shared object storage before increasing concurrency, requiring high availability, or running multiple instances.

Render documents that a persistent disk preserves only files under its mount path, cannot be shared with another service or multiple instances, and prevents zero-downtime deploys. The app writes every mutable business file under `/var/data`; built-in OEM templates and application code are part of the image. Startup initialization creates missing default records but no longer rewrites registered template paths or names.

The service returns `/api/health` only after a SQLite query succeeds. `/api/version` returns the application version and Render commit. API responses and HTML shells are `no-store`; hashed build assets are immutable. The service worker caches only the generic app shell and static assets, never `/api`, documents, authenticated business data, or reports.

## Provider and current cost estimate

Official provider references checked for this configuration:

- [Render Blueprint specification](https://render.com/docs/blueprint-spec.md), including Docker, `checksPass`, compute plans, disks, and secret placeholders.
- [Render deploys and CI integration](https://render.com/docs/deploys.md#integrating-with-ci).
- [Render persistent disks](https://render.com/docs/disks.md), including single-instance and snapshot limitations.
- [Render pricing](https://render.com/pricing.md).

The [current listed compute prices](https://render.com/pricing.md#compute) give this configuration a baseline of **US$27.50/month before tax and usage overages**:

| Item | Expected recurring cost |
| --- | ---: |
| Render web service, `1c-2g` (1 CPU, 2 GB RAM) | US$25/month |
| Persistent SSD, 10 GB at US$0.25/GB/month | US$2.50/month |
| Separate database | US$0; SQLite is on the persistent disk |
| Render Hobby workspace | US$0/month; this does not make the compute or disk free |
| Render bandwidth | First 5 GB/month included on Hobby; currently US$0.15/GB beyond that |
| Render `onrender.com` hostname and managed HTTPS | Included |
| Custom domain | Registrar renewal is separate; Render currently includes two custom-domain slots on Hobby |
| Gemini API | Usage-based; see [Google's live pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| n8n and email account | Separate provider/plan or company-hosting and email costs; see [n8n pricing](https://n8n.io/pricing/) and your email provider |

These are list-price estimates, not a quote. Confirm plan, tax, bandwidth, disk, region, account quotas, and any pricing changes in the dashboards before provisioning. Ten GB is a starting size; Render lets you grow a disk but not shrink it. Render's free web service is not suitable: free services can sleep, their filesystem is ephemeral, and they cannot use the paid persistent disk required here. There is no promise of permanent free production hosting.

Render preview environments require a Pro workspace (currently US$25/month before service compute), so this Blueprint does not create one. Pull requests instead run backend tests with isolated temporary SQLite data and no Gemini, email, or n8n credentials. Enable remote previews only if you later approve the additional workspace and preview compute costs.

## One-time setup

### 1. Prepare GitHub

1. The Blueprint is configured for `main`. Confirm that this is the intended production branch (change `render.yaml` and branch-protection settings if not), then commit and push this implementation. A push of uncommitted laptop edits is impossible: only committed objects are pushed.
2. In GitHub, protect `main` and require both checks:
   - `Backend tests (isolated SQLite)`
   - `Frontend build and PWA validation`
3. Do not add a second deploy action or Render deploy hook to GitHub Actions. Render is the only deploy system; its `checksPass` trigger waits for the GitHub checks.

The workflow in [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) runs the full backend unittest suite, builds Vite from source with `npm ci`, and checks the manifest, PNG dimensions, maskable icon, and versioned service worker. It never uses a laptop-built `frontend/dist`.

### 2. Create the Render service

1. Create a Render account and connect the GitHub account that owns the private application repository.
2. In the Render Dashboard choose **New → Blueprint**, select this repository and its `main` branch, then review the resources from [`render.yaml`](./render.yaml).
3. Confirm the plan is `1c-2g`, the region is `Singapore`, the persistent disk mount is `/var/data` at 10 GB, and auto-deploy is **After CI Checks Pass** (`checksPass`). Do not change the service to multiple instances or use a free instance.
4. When Render prompts for the `sync: false` variables, set the Gemini key and the final public HTTPS origin. If email is not ready yet, leave the three n8n values empty and do not configure Gmail credentials in production.
5. Wait for the Docker build and `/api/health` probe to finish. Render provisions the service URL and managed TLS. Confirm the service reports **Live** before creating employee accounts.

Use the provided `onrender.com` URL initially. For a company domain, add it to the service's **Settings → Custom Domains**, configure the DNS records Render provides, wait for managed TLS, and update `PUBLIC_APP_ORIGIN` to the final `https://` origin. Do not include a path or trailing slash in that variable. After changing environment variables choose **Save, rebuild, and deploy** or **Save and deploy** as appropriate.

### 3. Configure runtime variables

Set secrets in **Render Dashboard → service → Environment**; never put them in React code, Git, Docker build arguments, or the service worker.

| Variable | Production value |
| --- | --- |
| `APP_ENV` | `production` (Blueprint) |
| `PDI_DATA_DIR` | `/var/data` (Blueprint; SQLite becomes `/var/data/pdi_system.db`) |
| `SESSION_SECRET` | Generated 256-bit value from the Blueprint; keep it private |
| `SESSION_MAX_AGE_SECONDS` | `28800` (8-hour signed session) |
| `PUBLIC_APP_ORIGIN` | Exact public HTTPS origin, e.g. `https://yathi-pdi.onrender.com` |
| `GEMINI_API_KEY` | Secret from the company Google AI Studio account |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` by default; change only to a currently supported model |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MiB) |
| `N8N_WEBHOOK_URL` | Company-owned production HTTPS webhook; leave blank until ready |
| `N8N_WEBHOOK_TOKEN` | Independently generated bearer secret shared with the n8n Header Auth credential |
| `N8N_FROM_EMAIL` | Verified company sender address used by the email workflow |
| `LOG_LEVEL` | `INFO` unless operational troubleshooting requires otherwise |

`PDI_DATABASE_PATH`, `PDI_UPLOAD_DIR`, `PDI_REPORTS_DIR`, and `PDI_TEMPLATE_STORAGE_DIR` are optional overrides. Leave them unset so the app stores the database and all business files under `/var/data`. The application has no `DATABASE_URL`: this initial deployment is SQLite, not PostgreSQL.

Create a Gemini key in the company-owned [Google AI Studio](https://aistudio.google.com/app/apikey) account. Google bills Gemini separately by model and usage. Gemini calls stay on the backend; the frontend receives neither the key nor document-extraction responses from the service worker cache.

### 4. Set up the first administrator

In the Render Dashboard open the service's **Shell** and run:

```sh
python -m backend.create_admin
```

Enter the administrator's work email, name, and a unique password of at least 12 characters at the prompts. No credential is hard-coded or echoed into this guide. Sign in at the service URL, open **Employees**, and create inspector, approver, and additional administrator accounts. Prefer separate accounts and least privilege. Passwords are stored as Argon2 hashes; the signed, HTTP-only session expires after eight hours. API routes enforce roles even if someone bypasses the UI.

### 5. Migrate existing SQLite business data (if needed)

The PWA includes an administrator-only, app-consistent ZIP backup/import for the existing SQLite database and files referenced by it. The archive is confidential and contains purchase orders, inspection details, report workbooks/PDFs, template files, employee hashes, and customer metadata.

1. Back up the current local application before changing or moving its files.
2. From the repository root, copy `.env.example` to `backend\.env`. Keep any real keys only in this ignored local file or environment variables.
3. Run `python -m backend.create_admin` once for the local data, then start `python -m backend.main` in another terminal. Sign in and open **Employees → Download backup**. Store the ZIP in an approved, encrypted, access-controlled location. Do not email it or commit it.
4. Sign in to the new cloud service as the administrator created in step 4, open **Employees → Business data backup**, select the ZIP, and confirm the one-time import.
5. The import is deliberately limited to an otherwise untouched new cloud app: no business records, customer records, extra employee-registered templates, or files in user-template storage. It keeps existing cloud accounts, imports other source employees whose email is not already present, and copies files under unique names. It validates the SQLite integrity, runs versioned migrations, and rewrites stored file paths before replacing the initial database.
6. Confirm representative inspections, workbook/PDF downloads, and employee logins before inviting everyone.

Deployment initialization does not import the laptop's ignored SQLite database and does not overwrite registered template files. If the cloud app already has data, do **not** retry this one-time import or reset the disk. Use a Render disk snapshot for full-volume recovery or provision a separate empty service and restore there.

## Daily release workflow

1. Edit locally.
2. Test locally using the locked dependencies below; do not set production email credentials in the test environment.
3. Commit the tested changes.
4. Push/merge the commit to `main`.
5. GitHub Actions runs backend tests and the frontend build/PWA checks with isolated test data.
6. After all checks pass, Render builds the Docker image (including `npm ci` and `vite build`) from that commit, starts the single instance, and checks `/api/health`.
7. When the deployment is healthy, connected devices check for the new service worker on app open, foreground, and every five minutes. Users see **“Update available. Save your work and reload.”** and apply it themselves. Dirty inspection/report edits disable the reload button.

Unsaved laptop edits are not deployment triggers. Backend changes apply when Render brings up the new service. Frontend changes reach connected installed devices only after the user applies the available update; closed or offline devices check after they reopen/reconnect. Application code deployment does not synchronize business records between environments or devices—the server-side persistent database is shared separately.

## PWA installation and offline behavior

- **Android:** open the HTTPS app URL in Chrome; choose the install prompt or Chrome menu → **Install app** / **Add to Home screen**.
- **Windows:** open the URL in Chrome or Edge; use the address-bar install icon or browser menu → **Install this site as an app**.
- Browser menu wording varies. Install is available only in supported browsers and over HTTPS (localhost is the development exception).
- The service worker's release-specific cache keeps prior static asset caches and detects Vite chunk failures with a save-before-reload recovery prompt. The browser may evict caches. Reconnecting and reloading recovers assets from the service.
- Offline mode is only an application-shell fallback with a clear connection message. Upload, Gemini extraction, review save, approval, report generation, and downloads require backend/network access. **Offline report generation is not supported.**
- Do not use shared or public devices for confidential inspections. Sign out when finished.

## Roles, review, and printing

| Role | Main capabilities |
| --- | --- |
| Inspector | Upload requirements, review extracted fields, create inspections, edit draft reports |
| Approver | Review and approve reports; complete approval-gated actions |
| Administrator | Manage employee accounts and templates; includes application operations |

Extracted purchase-order data remains editable and must be reviewed before report generation. If another user has saved since an editor loaded, saving or approving with the old revision returns HTTP 409; reload and reconcile rather than overwriting the newer inspection.

Cloud code cannot reach a Windows spooler or company printer. The app opens/downloads the PDF, then the employee chooses the device's available print action. The application records no successful physical print merely because the PDF opened or downloaded.

## n8n and company email

The repository previously had an empty `n8n` folder; there was no workflow to adapt. The backend now supports a bearer-authenticated HTTPS webhook and the setup in [`n8n/README.md`](./n8n/README.md) provides the Code-node attachment conversion and safe workflow outline. Run n8n in n8n Cloud or on a company-managed, publicly reachable HTTPS host. `localhost` on Render cannot connect to n8n on an office laptop. Keep company email credentials in n8n's credential store. Configure the Respond to Webhook node after the email send so the PDI UI does not report success until the email node succeeds.

No email is sent in CI or staging. Do not test with customer recipients. Base64-encoded PDF attachments expand the request: n8n documents a 16 MiB default webhook payload limit. Self-hosted n8n should be configured for at least 40 MiB for the app's 25-MiB upload ceiling, subject to available memory; confirm n8n Cloud limits before enabling larger report batches.

## Backup, restore, monitoring, and rollback

- Use **Employees → Download backup** regularly and store the ZIP outside Render in an encrypted, access-controlled location with an appropriate retention policy. Restrict its use to administrators.
- Render automatically takes daily persistent-disk snapshots and retains them for seven days. These are useful for short-term recovery, not an off-provider backup. Restoring a snapshot replaces the whole disk state and discards all later writes.
- A ZIP restore can only be imported into a new, otherwise untouched app. For disaster recovery, either restore a Render disk snapshot or create a separate empty service/disk, set secrets, create the initial admin, import the ZIP before adding records/templates, verify it, and then move the custom domain when ready.
- Check the Render service's **Events**, **Deploys**, **Logs**, **Metrics**, and **Disk** pages. A failing build, migration/startup, or health probe prevents the new build from becoming live and Render retains the previous successful deploy. Application logs contain operational messages, not document bodies; do not enable request-body logging.
- To roll back application code, use **Deploys → Rollback** for the last known-good deploy. Render documents that a dashboard rollback automatically disables auto-deploys; after fixing the issue, re-enable automatic deploys in **Settings**. The disk and its current data are not rolled back with code. Database migrations must remain backward compatible with the code version you intend to run; code rollback cannot undo a data/schema migration.
- Before schema-changing releases, download a backup and test rollback compatibility. If a rollback requires restoring a disk snapshot, coordinate a maintenance window: all writes after that snapshot are lost.

## Locked local checks

The repository pins Node 22 in [`frontend/.nvmrc`](./frontend/.nvmrc), Python 3.12 in [`.python-version`](./.python-version), frontend packages in `frontend/package-lock.json`, and backend runtime/transitive packages in `backend/requirements.lock`. The CI-only test client is in `backend/requirements-dev.lock`.

From the repository root in PowerShell:

```powershell
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
```

If dependency versions change intentionally, update the exact direct versions in `backend/requirements.txt`, install `backend/requirements-tools.txt`, and regenerate both locks with `pip-compile`; review and test both lock diffs. The frontend lock is updated through npm and `npm ci` must pass before committing.

## Not yet verified in a real deployment

No cloud account or paid resource was created. GitHub connection, Render Blueprint creation, DNS/custom domain, production secrets, an actual production deploy, external backup storage, n8n/email credentials, and customer delivery require company account access and explicit company setup. CI and local browser checks do not prove installation on a physical Android device; verify the installed PWA on Android Chrome and Windows Chrome/Edge after the first HTTPS deployment.

