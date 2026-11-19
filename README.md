# Yathi Pumps PDI Automation System

A Pre-Delivery Inspection (PDI) report automation platform for **Yathi Pumps Pvt. Ltd.** that can be deployed as one installable Progressive Web App (PWA) for employees:
- **Havells** (HIL)
- **Crompton** (CGCEL)
- **KSB** (KSB Pumps / KBL)
- **KOEL** (Kirloskar Oil Engines Limited)

---

> **On-premises deployment:** See the [Windows LAN deployment guide](./deployment/windows/README.md) for the company-host setup, internal HTTPS, scheduled startup, backups, PWA installation, safe updates, and acceptance checklist. The [Render guide](./DEPLOYMENT.md) is a separate optional cloud deployment and is not required for the Windows-host setup.

## 1. System Overview

- **Template Preservation:** Generated workbooks start from the registered OEM template. Its layout, predefined inspection criteria, existing values, formulas, and styles are preserved; only supplied/extracted order details are written into their mapped cells.
- **Customer OEM Selection:** Choose between **Havells**, **Crompton**, **KSB**, and **KOEL**. The engine selects the corresponding customer PDI template preserving the exact structure, formatting, formulas, Indian Standards (`IS 9079/8472/...`), sampling plan (`IS 2500 / S2`), and 56 inspection criteria.
- **Havells Surface Pump Reference:** Every Havells model uses the included Surface Pump report format. Model, SKU, PO, and allocated lot details are populated per model, while the registered inspection readings and criteria are retained.
- **Required Image-Based Extraction:** Upload a purchase order/requirement before generating. Google Gemini reads the customer, product, model, SKU, PO number, and lot size, then fills the editable fields. Review and correct the extracted values, then click **Generate**. The app never creates a job automatically during extraction. Unreadable required values stay blank and are flagged for review.
  - **Model Name** (Cell `D4` with prefix `Model Name : `)
  - **SKU No.** (Cell `C4`)
  - **PO Number** (Cell `C5`)
  - **Lot Size / Qty** (Cell `D5` with prefix `Lot Qty : `)
  - **PO Total Qty** (Cell `C6`)
  - **Inspection Date** & **Dispatch Date** (Cells `H2`, `J2`) only when supplied or readable
  - Existing inspection checklist, observation values, and judgment in the selected template are retained
- **Report Generation:** Havells gets 1–5 editable workbooks per model based on lot size. Other customers get one workbook per model for the full lot. The original Excel templates and their formatting are preserved.
- **Interactive In-Browser Editor:** Excel-like grid preview and live editor for header metadata and all 56 checkpoint observation readings (including multi-sample columns G to K for electrical/hydraulic performance tests).
- **Havells J1 Legal Checklist:** Generates one J1 checklist per Havells model/PO lot. After approving that model's PDI reports, review each checklist item, enter remarks and MRP, paste or select product evidence pictures for the carton, nameplate/labels, and technical specifications, then agree to the checklist before emailing.
- **Export, Print & Email:**
  - Download individual `.xlsx` reports, bundled `.zip` archives, and ReportLab landscape A4 `.pdf` copies.
  - Open/download PDF files and print using the employee's device; the cloud server does not access company printers.
  - Approval-gated email dispatch through a company-owned n8n workflow (or explicitly configured local SMTP).

---

## 2. Customer Templates & Coordinates

| Field Key | Report Cell | Format / Prefix Rule |
| :--- | :---: | :--- |
| `supplier_name` | **`C3`** (merged `C3:D3`) | `Yathi Pumps Pvt. Ltd.` |
| `supplier_location`| **`F3`** | `Coimbatore, Tamil Nadu` |
| `sku_no` | **`C4`** | Input SKU No. (or `SKU / S/N: ...`) |
| `model_name` | **`D4`** | `prefix:Model Name : ` + Input Model |
| `po_number` | **`C5`** | Input PO Number |
| `lot_qty` | **`D5`** | `prefix:Lot Qty : ` + Input Lot Size |
| `final_judgment` | **`E5` / `F5`** | Preserves the registered template's value unless explicitly changed |
| `po_total_qty` | **`C6`** | Input PO Total Qty |
| `inspected_by` | **`D6`** | Inspector label; name only when supplied |
| `reject_reason` | **`F6`** | Recorded if judgment is Reject |
| `total_dispatched_qty`| **`C7`** | Residual and dispatch quantities |
| `approved_by` | **`D7`** | Approver label; name only when supplied |
| `residual_qty` | **`C8`** | Numeric residual |
| `inspection_date`| **`H2`** | `prefix:Inspection Date : \n` + Date |
| `lot_dispatch_date`| **`J2`** | `prefix:Lot Dispatch Date : ` + Date |

---

## 3. Local development on Windows

Use Python 3.12 and Node 22. From the repository root in PowerShell:

```powershell
Copy-Item .env.example backend\.env
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.lock
backend\.venv\Scripts\python.exe -m backend.main
```

In another terminal:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:5173` for frontend development or `http://127.0.0.1:8000` for the integrated local app. The Vite development server proxies `/api` to FastAPI. Keep `.env` files and local business data out of Git. The production PWA requires HTTPS; local HTTP is for development only.

With `APP_ENV=development` on the same PC, the app opens directly on the dashboard and provides a Backups page. Hosted deployments use employee sign-in and require administrator setup.

### Gemini API

Create an API key in [Google AI Studio](https://aistudio.google.com/app/apikey), then put it in `backend/.env` or set it in the process environment. Do not commit or share the key. Example `backend/.env`:

```text
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_TIMEOUT_SECONDS=30
GEMINI_EXTRACTION_TIMEOUT_SECONDS=90
```

The model defaults to `gemini-3.5-flash-lite`, which is listed in the [current Gemini model documentation](https://ai.google.dev/gemini-api/docs/models). Upload a JPG/PNG image, searchable PDF, or XLSX requirement. The backend sends the image/text to Gemini's multimodal API for extraction. Review/edit the extracted fields and click **Generate**. The template's predefined inspection criteria and values remain intact. The app never infers lot size from PO total quantity. Text-based PDFs are read from their text layer; scanned PDFs rely on embedded page images. Gemini returns schema-constrained JSON, and images are orientation-corrected and resized to a maximum 1280 px before sending. Document extraction uses `GEMINI_EXTRACTION_TIMEOUT_SECONDS` (90 seconds by default); a timeout is shown explicitly and does not trigger a second full-duration model request.

### Report counts and quantity allocation

The table applies to Havells. For every other customer, each model gets one workbook with its full lot quantity.

| Uploaded lot size | Workbooks | Quantity recorded in each workbook |
| --- | ---: | --- |
| 1–10 | 1 | Entire lot |
| 11–100 | 1 | Entire lot |
| 101–1,200 | 2 | Even split |
| 1,201–2,500 | 3 | Even split |
| 2,501–4,000 | 4 | Even split |
| Greater than 4,000 | 5 | Even split |

When a split has a remainder, the first reports receive one extra unit each (for example, lot 101 becomes 51 and 50). The quantities recorded across all workbooks sum to the original lot size.

### AI Chat Assistant
Use the floating **AI Assistant** button to ask about any part of the application, including workflows, features, report rules, settings, integrations, errors, troubleshooting, limitations, and read-only live status summaries. You can type report requirements or attach a PO/requirement file (including DOCX), review the extracted customer/model/SKU/PO/lot details, and create draft PDI reports. You can also attach an existing searchable PDF, XLSX, or DOCX report and ask for an analysis download; ask for Word/DOCX or PDF (PDF is the default), or request both for a ZIP download. To analyze reports already in the app, identify them by report code, customer, model, SKU, PO number, or date, or explicitly ask to analyze all reports. At most 20 reports can be analyzed at once. Analysis is advisory, does not alter or approve the source report, and is available as a downloadable document. The chat provides Excel and PDF links for generated PDI drafts; reports remain **Awaiting Review** and are never auto-approved, printed, or emailed. Havells generation also creates its J1 checklist. The configured Gemini API powers chat, requirement extraction, and requested report analysis. The backend supplies a curated application guide, active template/mapping metadata, and aggregate counts by date/status/customer/model; those summaries exclude credentials and customer contact details. If you attach a requirement or request report analysis, the relevant document/report contents are sent to Gemini for that task. Chat messages and analysis documents are not saved to inspection records. Ask for a PDF comparing today's and yesterday's reports to create a downloadable summary from the live database. If app details are not included in the assistant's reference, it will say so rather than guess. Verify extracted details and AI analyses before making PDI decisions. Chat and AI report tasks require `GEMINI_API_KEY`.

### Email and printing

Production email is configured through a company-owned, HTTPS n8n workflow; the n8n instance cannot run only on an office laptop's `localhost`. See the [n8n workflow setup](./n8n/README.md). Local SMTP is optional and should never point automated tests or staging at customer recipients. Email is approval-gated and includes the appropriate generated report PDFs and, for Havells, agreed J1 PDFs. Printing opens or downloads PDFs for the employee's device; a cloud server cannot access a Windows printer.

---

## 4. Run the workflow checks

From the repository root:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
Set-Location frontend
npm.cmd ci
npm.cmd run build
```

