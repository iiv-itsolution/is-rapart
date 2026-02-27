from __future__ import annotations

import mimetypes
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from email.utils import formatdate, make_msgid

from django.conf import settings


class SmtpNotConfigured(RuntimeError):
    pass


def _get_smtp_settings():
    host = getattr(settings, "EMAIL_SMTP_HOST", None)
    port = int(getattr(settings, "EMAIL_SMTP_PORT", 0) or 0)
    user = getattr(settings, "EMAIL_SMTP_USER", None)
    password = getattr(settings, "EMAIL_SMTP_PASSWORD", None)
    use_tls = bool(getattr(settings, "EMAIL_SMTP_USE_TLS", True))

    if not (host and port and user and password):
        raise SmtpNotConfigured(
            "SMTP is not configured. Set EMAIL_SMTP_HOST/PORT/USER/PASSWORD in local_settings.py"
        )

    return host, port, user, password, use_tls


def send_reply_email(
    *,
    from_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    attachments,  # Iterable[UploadedFile]
    in_reply_to: str | None,
    references: str | None,
):
    host, port, user, password, use_tls = _get_smtp_settings()

    msg = MIMEMultipart("mixed")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    message_id = make_msgid(domain=from_email.split("@")[-1])
    msg["Message-ID"] = message_id

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    msg.attach(MIMEText(body_text or "", "plain", "utf-8"))

    for f in attachments or []:
        filename = getattr(f, "name", "attachment")
        content_type = getattr(f, "content_type", None) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, subtype = content_type.split("/", 1) if "/" in content_type else ("application", "octet-stream")

        part = MIMEBase(maintype, subtype)
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename=\"{filename}\"")
        msg.attach(part)

    server = smtplib.SMTP(host, port, timeout=30)
    try:
        if use_tls:
            server.starttls()
        server.login(user, password)
        server.sendmail(from_email, [to_email], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass

    return message_id
