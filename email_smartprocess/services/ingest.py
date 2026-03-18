from __future__ import annotations

from email.utils import getaddresses
from dateutil.parser import parse
from django.conf import settings
from django.utils import timezone

from email_smartprocess.models import EmailMessage, EmailThread
from email_smartprocess.services.bitrix_activity import (
    ensure_activity,
    ensure_smartprocess_item,
    touch_thread_aggregates,
    update_activity,
)
from email_smartprocess.services.threading import compute_thread_id, normalize_message_id


def _format_recipients(value: str) -> str:
    emails: list[str] = []
    for _, addr in getaddresses([value or ""]):
        addr = (addr or "").strip()
        if addr and "@" in addr:
            emails.append(addr)

    # de-dupe preserving order (case-insensitive)
    seen: set[str] = set()
    uniq: list[str] = []
    for addr in emails:
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(addr)
    return ", ".join(uniq)


def _get_header(email_obj, *names: str) -> str:
    for name in names:
        try:
            value = email_obj.get(name)
        except Exception:
            value = None
        if value:
            return value
    return ""


def _resolve_thread_from_reply_headers(email_obj) -> EmailThread | None:
    # Prefer References, then In-Reply-To. Some clients may omit/alter the first reference,
    # but include a later Message-ID from the same thread.
    references = _get_header(email_obj, "references", "References")
    if references:
        for raw in [p for p in references.split() if p]:
            mid = normalize_message_id(raw)
            if not mid:
                continue
            msg = EmailMessage.objects.select_related("thread").filter(message_id=mid).first()
            if msg and msg.thread_id:
                return msg.thread

    in_reply_to = _get_header(email_obj, "in-reply-to", "In-Reply-To")
    if in_reply_to:
        mid = normalize_message_id(in_reply_to)
        if mid:
            msg = EmailMessage.objects.select_related("thread").filter(message_id=mid).first()
            if msg and msg.thread_id:
                return msg.thread

    return None


def _ensure_aware(dt):
    if not dt:
        return timezone.now()
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def ingest_email(
    *,
    email_obj,
    sender: str,
    subject: str,
    body_text: str,
    body_html: str,
    message_datetime,
    message_id_fallback: str,
):
    msg_id = normalize_message_id(email_obj.get("message-id") or email_obj.get("Message-ID") or "")
    msg_id = msg_id or message_id_fallback

    if EmailMessage.objects.filter(message_id=msg_id).exists():
        return None

    thread_id = compute_thread_id(email_obj)
    thread = EmailThread.objects.filter(thread_id=thread_id).first()
    if not thread:
        thread = _resolve_thread_from_reply_headers(email_obj)
    if not thread:
        thread, _ = EmailThread.objects.get_or_create(thread_id=thread_id)

    message_datetime = _ensure_aware(message_datetime)
    to_emails = _format_recipients(email_obj.get("to") or email_obj.get("To") or "")
    cc_emails = _format_recipients(email_obj.get("cc") or email_obj.get("Cc") or "")

    EmailMessage.objects.create(
        thread=thread,
        message_id=msg_id,
        sender=(sender or "")[:255],
        to_emails=to_emails,
        cc_emails=cc_emails,
        subject=(subject or "")[:255],
        body_text=body_text or "",
        body_html=body_html or "",
        created_at=message_datetime,
    )

    touch_thread_aggregates(thread, sender=sender or "", subject=subject or "", message_datetime=message_datetime)

    title = (subject or "").strip() or f"Email thread {thread.thread_id}"

    try:
        if not thread.smart_process_item_id:
            ensure_smartprocess_item(thread, title=title)

        if not thread.activity_id:
            ensure_activity(thread)
        else:
            update_activity(thread)
    except Exception as exc:
        ilogger = getattr(settings, "ilogger", None)
        if ilogger:
            ilogger.exception("email_smartprocess_bitrix_error", repr(exc))
        if settings.DEBUG:
            raise

    return thread


def parse_message_datetime(email_obj, fallback_dt):
    date_str = email_obj.get("date") or email_obj.get("Date")
    if not date_str:
        return _ensure_aware(fallback_dt)
    try:
        dt = parse(date_str)
    except Exception:
        return _ensure_aware(fallback_dt)
    return _ensure_aware(dt)
