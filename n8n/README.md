# Company email workflow for PDI

The repository previously had an empty `n8n` folder; there was no workflow to adapt. The backend now sends approved report PDFs and, where applicable, the agreed J1 checklist PDFs to a company-owned n8n webhook. This folder contains the Code-node script for turning that payload into n8n binary attachments.

## Host and secure the workflow

Run n8n in n8n Cloud or as an independently managed service on a company computer that the PDI host can reach. It must start without VS Code and have its own persistent configuration, restart policy, TLS, access controls, updates, execution-data retention, and backups. If it runs on another cloud server, that server's `localhost` is not the office computer; use the actual reachable HTTPS webhook URL. Do not expose an office n8n instance directly to the public internet. If n8n runs on the PDI host, use a separate service/listener and keep its administration access restricted.

There is no exported n8n workflow in this repository to import or adapt. The `n8n` folder contains only the payload conversion code below; the company must create, secure, and activate its own workflow.

In n8n:

1. Create a **Webhook** trigger with method `POST`, a stable path such as `pdi-customer-email`, and **Header Auth** credentials. Set the header name to `Authorization` and the value to `Bearer <the independently generated secret>`. Use the production webhook URL, not the temporary test URL.
2. Add a **Code** node, set it to run once for all items, and paste [`email-payload-code.js`](./email-payload-code.js).
3. Add a **Send Email** node using a company-owned SMTP/email credential. Set the sender to the verified company mailbox (not to a value supplied by the webhook), recipient to `{{$json.to}}`, subject to `{{$json.subject}}`, and message body to `{{$json.message}}`. Set the attachment binary field names to `{{$json.attachmentFields}}`.
4. Configure the Webhook to respond using a **Respond to Webhook** node. Place that node after the email node and return HTTP 200 JSON such as `{"status":"sent"}` only after the email node completes. A failed send must return a non-2xx response; otherwise the PDI app could report a false success.
5. Activate the workflow only after configuration review. Test with an internal company-controlled recipient; never send customer mail during development, CI, or initial deployment checks.

The backend sends `Authorization: Bearer ...`, with fields `from`, `to`, `customer_name`, `subject`, `message`, and `attachments` (`fileName`, `mimeType`, `base64`). Use the configured company sender account in n8n. The app allows email only after the required report approvals and the Havells J1 checklist agreement.

The backend upload limit is 25 MiB, but base64 and JSON framing expand attachments. n8n's documented default Webhook payload limit is 16 MiB. For self-hosted n8n, set `N8N_PAYLOAD_SIZE_MAX` to at least 40 MiB and ensure the host has adequate memory; confirm the limit for your n8n Cloud plan before enabling large email batches. Otherwise lower the PDI upload limit or use smaller batches.

Webhook executions include confidential report content in their request payload. Disable saving successful, failed, and manual execution payloads where the n8n hosting plan supports it; enable execution pruning and keep credentials in n8n's credential store. Do not log request bodies or attachment data in Code nodes. Restrict workflow editing to administrators.

## App configuration

Set these variables in `C:\ProgramData\Yathi Pumps PDI\config\.env` on the PDI host, not in frontend files or the release ZIP:

```text
N8N_WEBHOOK_URL=https://<reachable-company-n8n-host>/webhook/pdi-customer-email
N8N_WEBHOOK_TOKEN=<same independently generated secret as Header Auth>
N8N_FROM_EMAIL=<verified company mailbox>
```

The host must be able to resolve and reach the webhook over HTTPS. Changing the webhook secret requires updating the n8n credential and the PDI host configuration together, then restarting the PDI task. Never disable TLS verification for an internal certificate; install the trusted company CA where the n8n runtime needs it. Keep customer email disabled until the workflow has been tested with a company-controlled recipient.

Official docs: [n8n Webhook node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/), [Respond to Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/), [n8n pricing](https://n8n.io/pricing/).
