from __future__ import annotations

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
    thread, _ = EmailThread.objects.get_or_create(thread_id=thread_id)

    message_datetime = _ensure_aware(message_datetime)

    EmailMessage.objects.create(
        thread=thread,
        message_id=msg_id,
        sender=(sender or "")[:255],
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

