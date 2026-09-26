"""Outbound email for magic-link sign-in (Q12 / Q23).

stdlib ``smtplib`` + ``ssl`` only. Sending happens on a small background
thread pool so the HTTP response time of ``/v1/auth/magic/request`` does not
depend on whether the account exists (a synchronous send would be a timing
oracle for user enumeration) or on SMTP latency.

Configuration (``backend/shared/config.py``): ``SMTP_HOST`` / ``SMTP_PORT`` /
``SMTP_USER`` / ``SMTP_PASSWORD`` / ``SMTP_FROM`` / ``SMTP_SECURITY``
(``starttls`` | ``ssl`` | ``none``) / ``MAGIC_LINK_BASE_URL``. An empty
``SMTP_HOST`` means mail is not configured: nothing is sent and a warning is
logged. The token itself is never logged.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from concurrent.futures import Future, ThreadPoolExecutor
from email.message import EmailMessage

from backend.shared.config import settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="magic-mail")


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def magic_link_url(token: str) -> str:
    # Fragment (#token=...) — browsers never send it to the server, so the
    # token cannot land in an access log or a proxy's Referer header.
    return f"{settings.MAGIC_LINK_BASE_URL}#token={token}"


def _build_message(to_addr: str, link: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "PatentMind 登入連結 / sign-in link"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_addr
    ttl = settings.MAGIC_LINK_TTL_MIN
    msg.set_content(
        f"請點擊以下連結登入 PatentMind（{ttl} 分鐘內有效，僅能使用一次）：\n"
        f"{link}\n\n"
        f"Click the link below to sign in to PatentMind (valid for {ttl} minutes, single use):\n"
        f"{link}\n\n"
        "若您沒有申請登入，請忽略此信。 / If you did not request this, ignore this email.\n"
    )
    return msg


def send_email(msg: EmailMessage) -> None:
    """Deliver one message synchronously (raises on SMTP failure)."""
    security = settings.SMTP_SECURITY.lower()
    timeout = settings.SMTP_TIMEOUT_SEC
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
    try:
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            server.close()


def _send_magic_link(to_addr: str, token: str) -> bool:
    try:
        send_email(_build_message(to_addr, magic_link_url(token)))
        logger.info("magic-link email sent")
        return True
    except (OSError, smtplib.SMTPException) as exc:
        # Never include the token (or the link) in the log line.
        logger.error("magic-link email delivery failed (%s)", exc.__class__.__name__)
        return False


def dispatch_magic_link(to_addr: str | None, token: str) -> Future | None:
    """Queue the magic-link email; returns the Future (None when not sent).

    ``to_addr`` None (unknown user / no address on file) and unconfigured SMTP
    both return None without sending — the caller's HTTP response is the same
    generic message either way.
    """
    if not to_addr:
        return None
    if not smtp_configured():
        logger.warning(
            "magic-link requested but SMTP is not configured (SMTP_HOST/SMTP_FROM "
            "empty) — no email sent"
        )
        return None
    return _executor.submit(_send_magic_link, to_addr, token)
