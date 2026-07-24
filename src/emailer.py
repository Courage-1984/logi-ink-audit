"""Secure SMTP dispatch for Excel audit reports with critical-failure summaries."""

from __future__ import annotations

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

DEFAULT_SMTP_SERVER: str = "smtp.gmail.com"
DEFAULT_SMTP_PORT: int = 587

REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "SMTP_SENDER_EMAIL",
    "SMTP_RECIPIENT_EMAIL",
    "SMTP_PASSWORD",
)

XLSX_MIME_MAINTYPE: str = "application"
XLSX_MIME_SUBTYPE: str = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def load_smtp_config() -> dict[str, str | int] | None:
    """
    Load SMTP settings from the environment.

    Returns None (and logs a warning) when required credentials are absent so
    the wider automation run can continue without crashing.
    """
    sender = (os.getenv("SMTP_SENDER_EMAIL") or "").strip()
    recipient = (os.getenv("SMTP_RECIPIENT_EMAIL") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    server = (os.getenv("SMTP_SERVER") or DEFAULT_SMTP_SERVER).strip() or DEFAULT_SMTP_SERVER
    port_raw = (os.getenv("SMTP_PORT") or str(DEFAULT_SMTP_PORT)).strip() or str(
        DEFAULT_SMTP_PORT
    )

    missing = [
        key
        for key, value in (
            ("SMTP_SENDER_EMAIL", sender),
            ("SMTP_RECIPIENT_EMAIL", recipient),
            ("SMTP_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        logger.warning(
            "SMTP credentials incomplete — skipping email dispatch. "
            "Missing or empty: %s. Set these via environment variables "
            "(see .env.example).",
            ", ".join(missing),
        )
        return None

    try:
        port = int(port_raw)
    except ValueError:
        logger.warning(
            "Invalid SMTP_PORT value %r — falling back to %d.",
            port_raw,
            DEFAULT_SMTP_PORT,
        )
        port = DEFAULT_SMTP_PORT

    return {
        "sender": sender,
        "recipient": recipient,
        "password": password,
        "server": server,
        "port": port,
    }


def build_email_body(
    critical_summary: Sequence[str],
    *,
    base_url: str = "",
    delta: dict | None = None,
) -> str:
    """Construct the plain-text email body from critical failures and delta summary."""
    site_line = f"Target site: {base_url}\n" if base_url else ""
    delta = delta or {}
    delta_line = str(delta.get("summary_line") or "").strip()
    delta_block = (
        f"Delta Summary: {delta_line}\n\n"
        if delta_line
        else ""
    )

    if not critical_summary:
        return (
            f"{site_line}"
            f"{delta_block}"
            "All critical SEO and GEO checks passed successfully.\n\n"
            "The full Excel workbook is attached for detailed review.\n"
        )

    bullets = "\n".join(f"• {line}" for line in critical_summary)
    return (
        f"{site_line}"
        f"{delta_block}"
        "Critical SEO and GEO failures detected:\n\n"
        f"{bullets}\n\n"
        "The full Excel workbook is attached for detailed review.\n"
    )


def send_audit_report(
    file_path: str,
    critical_summary: list,
    *,
    base_url: str = "",
    delta: dict | None = None,
) -> bool:
    """
    Email the Excel audit report with an embedded critical-failure summary.

    Builds a MIMEMultipart message, attaches the `.xlsx` workbook, and sends
    via STARTTLS SMTP. Returns True when sent, False when skipped or on error.
    Missing credentials log a warning and do not raise.
    """
    config = load_smtp_config()
    if config is None:
        return False

    path = Path(file_path)
    if not path.is_file():
        logger.warning("Audit report not found at %s — skipping email dispatch.", path)
        return False

    subject_status = (
        "CRITICAL FAILURES"
        if critical_summary
        else "All critical checks passed"
    )
    subject = f"Logi-Ink audit report — {subject_status} — {path.name}"

    message = MIMEMultipart()
    message["Subject"] = subject
    message["From"] = str(config["sender"])
    message["To"] = str(config["recipient"])
    message.attach(
        MIMEText(
            build_email_body(critical_summary, base_url=base_url, delta=delta),
            "plain",
            "utf-8",
        )
    )

    attachment = MIMEBase(XLSX_MIME_MAINTYPE, XLSX_MIME_SUBTYPE)
    with path.open("rb") as handle:
        attachment.set_payload(handle.read())
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=path.name,
    )
    message.attach(attachment)

    try:
        with smtplib.SMTP(str(config["server"]), int(config["port"]), timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(str(config["sender"]), str(config["password"]))
            smtp.send_message(message)
    except smtplib.SMTPException as exc:
        logger.warning("SMTP dispatch failed: %s", exc)
        return False
    except OSError as exc:
        logger.warning("SMTP connection error: %s", exc)
        return False

    logger.info(
        "Audit report emailed to %s (%d critical failure line(s)).",
        config["recipient"],
        len(critical_summary),
    )
    return True
