# AGENTS.md

## Cursor Cloud specific instructions

This repo is a single Python CLI product (the **Logi-Ink Web Auditing Suite**). It crawls a live website, audits it for SEO/GEO/AEO/accessibility, and writes a formula-driven Excel workbook to `audit-reports/live-audit-DD-MM-YYYY.xlsx`. There is no web server, database, or listening port; the only runtime dependency is outbound HTTPS to the audited site (SMTP email dispatch is optional).

- Dependencies are installed by the startup update script (`pip install -r requirements.txt`), so you should not need to reinstall them.
- Use `python3`, not `python` — this VM has no `python` alias, so the `python ...` commands in `README.md` and `.cursor/environment.json` must be run as `python3 main.py ...`.
- Run the app / core flow: `python3 main.py --base-url https://logi-ink.co.za --max-pages 5 --skip-email -v` for a fast bounded run. Drop `--max-pages`/`--skip-email` for a full audit. See `README.md` for all CLI flags and exit codes.
- No lint, test, or build tooling is configured (no `pyproject.toml`/`setup.py`, no `pytest`/`tests/`, no linter config). The practical validation is a bounded audit run that exits `0` and writes a workbook under `audit-reports/`.
- SMTP email is optional: with no `SMTP_*` secrets set it logs a warning and still writes the report. Use `--skip-email` to skip dispatch entirely.
- Generated `*.xlsx` reports are gitignored (see `.gitignore`); don't commit them.
