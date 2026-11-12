# Maya → Telegram monitor

Reads only authenticated mail from `maya@mailtase.co.il` using IMAP EXAMINE and BODY.PEEK[]. Opens the original Maya report link from data-mce-href, renders the report page with Chromium, discovers its HTML/PDF attachments, and submits the **public original documents** to Gemini. PDFs are sent intact, including scanned pages and slides; there is no guessed PDF path or silent page truncation. Private email bodies and mailbox credentials are not sent to Gemini.

Classification is structured and validated. Unknown results remain retryable. SQLite stores the mail cursor, report IDs, previous material summaries, pending analyses and Telegram outbox. Failure is never recorded as non-material. Model-based comparison handles translations and corrections against the latest 100 material reports; this is best-effort semantic dedup, not a guarantee. A failed report is retried every 15 minutes, with one qualified notice after three failed attempts.

## Deployment (not yet performed)

Use the Dockerfile for a **single** Render Background Worker. The existing native Python service may need migration to Docker; inspect its configuration before doing so. Do not run the old and new worker simultaneously against the same bot. Attach a persistent disk at `/var/data` and ensure the worker user can write it. Do not assume ephemeral Render storage will retain state across deploys. Adding/migrating a service or disk may affect cost and needs an explicit deployment decision.

Keep existing secrets in Render:
- GMAIL_USER
- GMAIL_APP_PASSWORD
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- GEMINI_API_KEY

Additional required values:
- STATE_DB=/var/data/maya.sqlite3
- GEMINI_MODEL: an available PDF-capable GenerateContent model for this account. Set an explicit model after checking availability; no hardcoded retired model or automatic fallback.

Optional GMAIL_FOLDER defaults to INBOX. It must be the mailbox receiving Maya mail. Messages archived by Gmail filters before arrival in this folder are outside this folder's scope.

First start establishes a boundary at the latest Maya email and watches subsequent arrivals. It deliberately sends no history backlog. Existing pending jobs survive restart only with persistent storage. A changed mailbox UIDVALIDITY stops scanning with a log warning until an operator reviews the mailbox and rebaselines it; queued work still runs.

Start: `python main.py`. No startup Telegram message and no Telegram command polling are implemented. The bot pushes analyzed reports automatically. `/check` is not implemented in this version.

## Validation

`python -m unittest discover -v`

Public-document discovery smoke check (no mail, Gemini or Telegram calls):
`python main.py --inspect https://maya.tase.co.il/reports/details/1778748`

After deployment, verify document discovery, the chosen model's structured PDF response, persistence across restart, read-only Gmail flags, and one delivery to the configured private chat. These live checks require the selected Render workspace and secrets already stored there; they have not been executed by the local tests.

## Limits

12 attachments, 12 MiB per file and 18 MiB combined encoded input. Larger or inaccessible reports remain unknown and retry; they are never truncated and called non-material. The AI has no trading/email tools and no external browsing tools; it must disclose missing company baselines instead of inventing them. Semantic materiality remains a judgment and can be wrong.

Telegram lacks an idempotency key for sendMessage. If the server accepts a message but the connection dies before acknowledgment (or the worker stops before persisting success), retry can produce a duplicate. Ordinary restarts and acknowledged deliveries are deduplicated. Single-message notifications avoid partial multipart delivery.

This worker is independent of the ChatGPT Maya automation. Deploying it does not modify or disable that task.
