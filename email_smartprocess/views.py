from __future__ import annotations

from email.utils import parseaddr

from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import EmailThread, EmailMessage
from .services.bitrix_activity import ensure_activity, ensure_smartprocess_item, update_activity
from .services.smtp_send import SmtpNotConfigured, send_reply_email


def thread_api(request, thread_id: str):
    thread = EmailThread.objects.get(thread_id=thread_id)
    messages = thread.messages.all().values(
        "message_id",
        "sender",
        "subject",
        "created_at",
    )
    return JsonResponse(
        {
            "thread_id": thread.thread_id,
            "messages_count": thread.messages_count,
            "last_message_date": thread.last_message_date,
            "messages": list(messages),
        },
        json_dumps_params={"ensure_ascii": False},
    )


def owner_thread_api(request):
    """Return latest thread_id by Bitrix Smart Process item id (ownerId)."""
    owner_id_raw = (request.GET.get("ownerId") or request.GET.get("owner_id") or "").strip()
    try:
        owner_id = int(owner_id_raw)
    except Exception:
        return JsonResponse({"ok": False, "error": "ownerId is required"}, status=400)

    thread = EmailThread.objects.filter(smart_process_item_id=owner_id).order_by("-updated_at").first()
    return JsonResponse(
        {"ok": True, "owner_id": owner_id, "thread_id": thread.thread_id if thread else None},
        json_dumps_params={"ensure_ascii": False},
    )


def _wrap_message_id(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return value
    return f"<{value}>"


def _guess_reply_to_email(thread: EmailThread) -> str:
    smtp_user = getattr(settings, "EMAIL_SMTP_USER", "") or ""
    smtp_user = smtp_user.strip().lower()

    for msg in thread.messages.order_by("-created_at"):
        _, addr = parseaddr(msg.sender or "")
        addr = (addr or "").strip().lower()
        if addr and addr != smtp_user:
            return addr

    raise ValueError("Cannot determine reply-to email from thread messages")


def _normalize_email(value: str) -> str:
    _, addr = parseaddr(value or "")
    addr = (addr or "").strip()
    if not addr or "@" not in addr:
        raise ValueError("Некорректный email")
    return addr


def _build_thread_context(request, thread: EmailThread, *, embed: bool):
    mode = (request.GET.get("mode") or "").strip().lower()
    open_reply = (request.GET.get("reply") or "").strip().lower() in ("1", "true", "yes", "y")
    if not mode:
        mode = "reply" if open_reply else "full"

    show_messages = mode in ("full", "view")
    show_form = mode in ("full", "reply")
    if mode == "reply":
        open_reply = True

    smtp_configured = all(
        getattr(settings, k, None)
        for k in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_SMTP_USER", "EMAIL_SMTP_PASSWORD")
    )

    default_subject = thread.last_subject
    if default_subject and not default_subject.lower().startswith("re:"):
        default_subject = f"Re: {default_subject}"

    try:
        default_to = _guess_reply_to_email(thread)
    except Exception:
        default_to = ""

    return {
        "thread": thread,
        "messages": thread.messages.all(),
        "smtp_configured": smtp_configured,
        "default_to": default_to,
        "default_subject": default_subject,
        "open_reply": open_reply,
        "embed": embed,
        "mode": mode,
        "show_messages": show_messages,
        "show_form": show_form,
    }


def thread_page(request, thread_id: str):
    try:
        thread = EmailThread.objects.get(thread_id=thread_id)
    except EmailThread.DoesNotExist:
        raise Http404("Thread not found")

    return render(request, "email_smartprocess/thread.html", _build_thread_context(request, thread, embed=False))


def thread_widget(request, thread_id: str):
    try:
        thread = EmailThread.objects.get(thread_id=thread_id)
    except EmailThread.DoesNotExist:
        raise Http404("Thread not found")

    return render(request, "email_smartprocess/thread.html", _build_thread_context(request, thread, embed=True))


def widget_page(request):
    """Widget page to be embedded into Bitrix configurable activity iframe.

    Expected query params:
    - thread_id=...
    - mode=history|compose (optional)
    """
    return render(
        request,
        "email_smartprocess/bitrix_activity_widget.html",
        {},
    )


def thread_ui(request, thread_id: str):
    """Compact UI to be opened from Bitrix (side panel / iframe).

    Modes:
    - ?mode=view  -> only messages
    - ?mode=reply -> only reply form
    """
    try:
        thread = EmailThread.objects.get(thread_id=thread_id)
    except EmailThread.DoesNotExist:
        raise Http404("Thread not found")

    ctx = _build_thread_context(request, thread, embed=True)
    if ctx["mode"] not in ("view", "reply"):
        ctx["mode"] = "view"
        ctx["show_messages"] = True
        ctx["show_form"] = False
    return render(request, "email_smartprocess/thread.html", ctx)


def bitrix_activity_widget(request):
    """Bitrix placement handler (DETAIL_ACTIVITY): embedded email UI without new tabs.

    Supports:
    - ?mode=history|compose
    - ?thread_id=... (optional, for opening from configurable activity buttons)
    """
    return render(
        request,
        "email_smartprocess/bitrix_activity_widget.html",
        {
            "app_domain": getattr(settings, "APP_DOMAIN", None) or getattr(settings, "DOMAIN", None) or "",
            "initial_mode": (request.GET.get("mode") or "").strip().lower(),
            "thread_id": (request.GET.get("thread_id") or "").strip(),
        },
    )


def bitrix_email_tab(request):
    """Bitrix DETAIL_TAB handler: embedded email UI inside Smart Process card.

    Supports:
    - ?mode=history|compose
    - ?thread_id=... (optional, for openRestApp/sidepanel opening)
    """
    return render(
        request,
        "email_smartprocess/bitrix_email_tab.html",
        {},
    )


@require_POST
def thread_send(request, thread_id: str):
    thread = EmailThread.objects.get(thread_id=thread_id)

    to_email_raw = (request.POST.get("to_email") or "").strip()
    subject = (request.POST.get("subject") or "").strip()
    body = (request.POST.get("body") or "").strip()
    files = request.FILES.getlist("files")
    embed = (request.POST.get("embed") or "").strip() == "1"
    mode = (request.POST.get("mode") or "").strip().lower()
    preserve_fields = mode != "reply"
    if not preserve_fields:
        # In reply mode "To" and "Subject" are fixed to avoid breaking the thread.
        to_email_raw = ""
        subject = ""

    if not body:
        return render(
            request,
            "email_smartprocess/thread.html",
            (
                {
                    **_build_thread_context(request, thread, embed=embed),
                    **({"default_to": to_email_raw, "default_subject": subject} if preserve_fields else {}),
                    "error": "Пустой текст сообщения",
                }
            ),
        )

    try:
        smtp_user = getattr(settings, "EMAIL_SMTP_USER", None)
        if not smtp_user:
            raise SmtpNotConfigured("EMAIL_SMTP_USER is not configured")

        if to_email_raw:
            to_email = _normalize_email(to_email_raw)
        else:
            to_email = _guess_reply_to_email(thread)

        in_reply_to = _wrap_message_id(thread.thread_id)
        references = in_reply_to

        message_id = send_reply_email(
            from_email=smtp_user,
            to_email=to_email,
            subject=subject or (f"Re: {thread.last_subject}" if thread.last_subject else "Re:"),
            body_text=body,
            attachments=files,
            in_reply_to=in_reply_to,
            references=references,
        )

        EmailMessage.objects.create(
            thread=thread,
            message_id=message_id.strip("<>") or f"out:{timezone.now().timestamp()}",
            sender=smtp_user,
            subject=subject,
            body_text=body,
            body_html="",
            created_at=timezone.now(),
        )

        thread.last_message_date = timezone.now()
        thread.messages_count = thread.messages.count()
        thread.last_sender = smtp_user[:255]
        thread.last_subject = (subject or thread.last_subject or "")[:255]
        thread.save(update_fields=["last_message_date", "messages_count", "last_sender", "last_subject", "updated_at"])

        if thread.activity_id:
            update_activity(thread)

    except SmtpNotConfigured as exc:
        return render(
            request,
            "email_smartprocess/thread.html",
            (
                {
                    **_build_thread_context(request, thread, embed=embed),
                    "smtp_configured": False,
                    **({"default_to": to_email_raw, "default_subject": subject} if preserve_fields else {}),
                    "error": str(exc),
                }
            ),
        )
    except Exception as exc:
        ilogger = getattr(settings, "ilogger", None)
        if ilogger:
            ilogger.exception("email_thread_send_error", repr(exc))
        return render(
            request,
            "email_smartprocess/thread.html",
            (
                {
                    **_build_thread_context(request, thread, embed=embed),
                    **({"default_to": to_email_raw, "default_subject": subject} if preserve_fields else {}),
                    "error": f"Ошибка отправки: {exc}",
                }
            ),
        )

    if embed:
        if mode in ("view", "reply"):
            return redirect("email_thread_ui", thread_id=thread.thread_id)
        return redirect("email_thread_widget", thread_id=thread.thread_id)
    return redirect("email_thread_page", thread_id=thread.thread_id)


@require_POST
def demo_create_activity(request):
    # Minimal prototype endpoint: create SP item + configurable activity bound to the SP item.
    # Allowed only in DEBUG unless EMAIL_DEMO_KEY is provided.
    demo_key = getattr(settings, "EMAIL_DEMO_KEY", "")
    if not settings.DEBUG and demo_key:
        provided = request.headers.get("X-DEMO-KEY") or request.POST.get("demo_key") or ""
        if provided != demo_key:
            return JsonResponse({"ok": False, "error": "Forbidden"}, status=403)

    thread_id = (request.POST.get("thread_id") or "").strip()
    title = (request.POST.get("title") or "").strip()

    if not thread_id:
        return JsonResponse({"ok": False, "error": "thread_id is required"}, status=400)

    thread, _ = EmailThread.objects.get_or_create(thread_id=thread_id)

    if not title:
        title = f"Email thread {thread.thread_id}"

    try:
        ensure_smartprocess_item(thread, title=title)
        ensure_activity(thread)
        return JsonResponse(
            {
                "ok": True,
                "thread_id": thread.thread_id,
                "smart_process_item_id": thread.smart_process_item_id,
                "activity_id": thread.activity_id,
            },
            json_dumps_params={"ensure_ascii": False},
        )
    except Exception as exc:
        ilogger = getattr(settings, "ilogger", None)
        if ilogger:
            ilogger.exception("demo_create_activity_error", repr(exc))
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
