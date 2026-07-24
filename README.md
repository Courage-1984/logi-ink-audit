# Logi-Ink Web Auditing Suite

Asynchronous Python toolkit that evaluates [https://logi-ink.co.za](https://logi-ink.co.za) across **Technical SEO**, **Generative Engine Optimisation (GEO)**, and **Answer Engine Optimisation (AEO)**.

The suite performs live HTTP fetching, static DOM parsing, structured-data validation, and writes a formula-driven Excel workbook under `audit-reports/`.

## Features

| Pillar | What is checked |
| --- | --- |
| **Technical SEO** | Status codes, redirects, latency, title/meta lengths, brand consistency, heading hierarchy (including skipped levels), image alt text, Open Graph tags (including expected asset paths), canonical correctness |
| **GEO** | JSON-LD schema extraction & validation (`Organization`, `LocalBusiness`, `Service`, `WebSite`, `BreadcrumbList`, …), South African localisation (`addressLocality` Pretoria, `addressRegion` Gauteng, `addressCountry` ZA, `priceCurrency` ZAR, `html lang=en-ZA`), semantic HTML landmarks, NAP consistency, `sameAs` entity links |
| **AEO** | Direct-answer readiness: definition patterns, key-value pairs, structured lists, standalone summary / lead blocks suitable for AI Search Overviews |
| **Technical / A11y** | Missing or empty `alt` attributes, `main` / `nav` / `header` landmarks, internal vs external link density (orphan-risk detection) |

## Project layout

```
logi-ink-audit/
├── main.py                  # CLI orchestrator
├── requirements.txt         # Pinned dependencies
├── README.md
├── .cursor/
│   └── environment.json     # Cursor Cloud Agent preparation
├── src/
│   ├── crawler.py           # Async sitemap + HTTP crawler (aiohttp)
│   ├── auditor_seo.py       # Technical SEO analyser
│   ├── auditor_geo_aeo.py   # GEO & AEO analyser + SA localisation
│   ├── auditor_technical.py # Accessibility, landmarks, link density
│   ├── emailer.py           # SMTP report dispatch (stdlib only)
│   └── reporter.py          # openpyxl Excel reporter
├── .env.example             # SMTP credential placeholders
└── audit-reports/           # Generated workbooks (live-audit-DD-MM-YYYY.xlsx)
```
## Requirements

- Python 3.11+ recommended (3.10+ supported)
- Network access to the target site

Pinned packages:

- `aiohttp`
- `beautifulsoup4`
- `lxml`
- `openpyxl`

## Local usage

```bash
# 1. Create and activate a virtual environment (recommended)
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run a full sitemap-driven audit
python main.py --base-url https://logi-ink.co.za
```

### Useful CLI options

```bash
# Limit concurrency / timeout
python main.py --concurrency 6 --timeout 20

# Cap pages during a smoke test
python main.py --max-pages 5 -v

# Audit specific URLs only (skips sitemap discovery)
python main.py --url https://logi-ink.co.za --url https://logi-ink.co.za/about

# Custom report directory
python main.py --output-dir ./audit-reports
```

Reports are written to:

```text
audit-reports/live-audit-DD-MM-YYYY.xlsx
```

### Workbook contents

1. **Overview** — target site, page count, and Excel formulae computing average SEO / GEO / AEO compliance plus operational flags (HTTP errors, missing schema, heading issues).
2. **Detailed Results** — one row per URL with status, latency, `HTML Lang`, missing alt counts, internal link counts, detected schema types, Local SEO Compliance (Pass/Fail), heading validity, NAP / `sameAs`, and flagged GEO/AEO gaps. Conditional formatting uses green (pass), amber (localisation / soft warnings), and red (failure).

## Email dispatch

After the workbook is written, the suite summarises **critical failures** and can email the report via SMTP (`src/emailer.py`).

Critical failures include:

- HTTP status ≥ 400
- Missing `<title>` or meta description
- Missing / empty image `alt` text
- Absent or malformed JSON-LD
- Failed South African localisation (`en-ZA`, ZAR, Pretoria / Gauteng / ZA)

Configure credentials from `.env.example` (never hardcode secrets):

```bash
# Copy and edit
cp .env.example .env

# Or export directly (PowerShell example)
$env:SMTP_SENDER_EMAIL="your-sender@example.com"
$env:SMTP_RECIPIENT_EMAIL="your-recipient@example.com"
$env:SMTP_PASSWORD="your-app-password-here"
$env:SMTP_SERVER="smtp.gmail.com"
$env:SMTP_PORT="587"
```

| Variable | Purpose | Default |
| --- | --- | --- |
| `SMTP_SENDER_EMAIL` | From address | *(required)* |
| `SMTP_RECIPIENT_EMAIL` | To address | *(required)* |
| `SMTP_PASSWORD` | SMTP password / app password | *(required)* |
| `SMTP_SERVER` | SMTP host | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |

If required SMTP variables are missing, the run **logs a warning and continues** (report still written). Use `--skip-email` to suppress dispatch when credentials are present.

The email body lists failures as `URL - Specific Error`, or states: *All critical SEO and GEO checks passed successfully.* The `.xlsx` is attached with the Office Open XML MIME type.

## Cursor Cloud Agent Automations

`.cursor/environment.json` prepares the cloud environment, defines SMTP placeholder env keys, and the default audit command:

```json
{
  "install": "pip install -r requirements.txt",
  "start": "python main.py --base-url https://logi-ink.co.za",
  "env": {
    "SMTP_SENDER_EMAIL": "your-sender@example.com",
    "SMTP_RECIPIENT_EMAIL": "your-recipient@example.com",
    "SMTP_PASSWORD": "your-app-password-here",
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": "587"
  }
}
```

When a Cursor Cloud Agent (or Automation) starts in this repository:

1. Dependencies are installed via `pip install -r requirements.txt`.
2. The agent runs `python main.py --base-url https://logi-ink.co.za`.
3. The Excel report is produced under `audit-reports/`.
4. If real SMTP secrets are configured in the cloud environment, the report is emailed with a critical-failure summary.

Ensure the cloud runtime has outbound HTTPS (crawl) and SMTP (email) access as needed.

## Architecture notes

- **Fetching** is fully asynchronous (`asyncio` + `aiohttp`) with a concurrency semaphore.
- **Parsing** uses BeautifulSoup + `lxml` only — no browser automation, keeping the dependency footprint light for local and cloud runs.
- **Sitemaps** are preferred (`/sitemap.xml`, index variants); if none are found the crawler falls back to same-host links on the homepage.
- **Spelling** in comments, logs, and user-facing text follows UK English (`optimisation`, `behaviour`, `analyser`).

## Exit behaviour

| Code | Meaning |
| --- | --- |
| `0` | Audit completed and report written |
| `1` | No pages fetched / fatal abort |
| `130` | Interrupted (`Ctrl+C`) |

## Licence

Private project tooling for Logi-Ink audits. Adjust as needed for your distribution model.
