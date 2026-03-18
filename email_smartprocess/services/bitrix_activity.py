from __future__ import annotations

from email.utils import parseaddr

from django.conf import settings
from django.utils import timezone

from integration_utils.bitrix24.models import BitrixUserToken


def _is_automated_sender(value: str) -> bool:
    _, addr = parseaddr(value or "")
    addr = (addr or "").strip().lower()
    if not addr:
        return False
    return any(
        addr.startswith(prefix)
        for prefix in (
            "mailer-daemon@",
            "postmaster@",
            "no-reply@",
            "noreply@",
            "do-not-reply@",
            "donotreply@",
        )
    )


def _one_line(value: str) -> str:
    return " ".join((value or "").split())


def _truncate(value: str, limit: int) -> str:
    value = value or ""
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _activity_header_title(thread) -> str:
    subject = _one_line(getattr(thread, "last_subject", "") or "")
    return _truncate(subject, 120) if subject else "Email-переписка"


def _activity_summary_value(thread) -> str:
    lines: list[str] = []
    try:
        messages = list(getattr(thread, "messages").order_by("-created_at")[:25])
    except Exception:
        messages = []

    for msg in messages:
        if _is_automated_sender(getattr(msg, "sender", "") or ""):
            continue
        sender = _one_line(getattr(msg, "sender", "") or "") or "?"
        body = _truncate(_one_line(getattr(msg, "body_text", "") or ""), 180)

        created_at = getattr(msg, "created_at", None)
        try:
            created_at = timezone.localtime(created_at) if created_at else None
        except Exception:
            pass
        ts = created_at.strftime("%d.%m %H:%M") if created_at else ""

        prefix = f"{ts} — {sender}: " if ts else f"{sender}: "
        lines.append(prefix + (body or ""))
        if len(lines) >= 10:
            break

    preview = "\n".join(lines) if lines else "Сообщений пока нет."
    return _truncate(preview, 1200)


def _get_admin_token():
    return BitrixUserToken.get_admin_token()


def _get_sp_entity_type_id(thread) -> int:
    configured = getattr(settings, "EMAIL_SP_ENTITY_TYPE_ID", None)
    if configured is not None:
        return int(configured)

    if thread.smart_process_entity_type_id:
        return int(thread.smart_process_entity_type_id)

    raise ValueError("EMAIL_SP_ENTITY_TYPE_ID is not configured")


def _get_activity_owner_type_id(entity_type_id: int) -> int:
    """Bitrix uses ownerTypeId for configurable activities.

    For Smart Process it may be equal to entityTypeId, but if your portal
    requires a different value, set EMAIL_SP_OWNER_TYPE_ID in local_settings.
    """

    configured = getattr(settings, "EMAIL_SP_OWNER_TYPE_ID", None)
    return int(configured) if configured is not None else int(entity_type_id)


def _icon_code() -> str:
    # Portal validates IconDto.code against an enum; pick a safe default.
    return getattr(settings, "EMAIL_ACTIVITY_ICON_CODE", None) or "mail-outcome"


def _app_base_url() -> str:
    domain = (getattr(settings, "APP_DOMAIN", None) or getattr(settings, "DOMAIN", None) or "").strip()
    if not domain:
        raise ValueError("APP_DOMAIN (or DOMAIN) is not configured")
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    return f"https://{domain}".rstrip("/")


def ui_url(thread_id: str, *, mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode not in ("view", "reply"):
        mode = "view"
    return f"{_app_base_url()}/email/ui/{thread_id}/?mode={mode}"


def _rest_app_id() -> str:
    app_settings = getattr(settings, "APP_SETTINGS", None)
    app_id = getattr(app_settings, "application_bitrix_client_id", None)
    if not app_id:
        raise ValueError("APP_SETTINGS.application_bitrix_client_id is not configured")
    return str(app_id)


def _open_rest_app_action(*, thread_id: str, mode: str, title: str) -> dict:
    """Open our Bitrix24 REST app in slider and navigate inside app to the needed UI.

    root_views.index handles PLACEMENT_OPTIONS / actionParams and redirects to /email/ui/<thread_id>/?mode=...
    """
    return {
        "type": "openRestApp",
        "id": _rest_app_id(),
        "actionParams": {
            # Redirect inside our app straight to /email/ui/... (no extra widget/tabs).
            "target": "email_ui",
            "thread_id": thread_id,
            "mode": mode,
        },
        "sliderParams": {
            "title": title,
            "width": int(getattr(settings, "EMAIL_ACTIVITY_SLIDER_WIDTH", 900)),
        },
    }


def _layout_variants(thread):
    """Clean configurable activity layout (no iframe).

    Opens UI in Bitrix slider (sidepanel) via link actions.
    """

    icon = {"code": _icon_code()}
    header_title = _activity_header_title(thread)
    summary_value = _activity_summary_value(thread)

    yield {
        "icon": icon,
        "header": {
            "title": header_title,
        },
        "body": {
            "logo": {"code": _icon_code()},
            "blocks": {
                "summary": {
                    "type": "largeText",
                    "properties": {
                        "value": summary_value,
                    },
                },
            },
        },
        "footer": {
            "buttons": {
                "reply": {
                    "title": "Ответить",
                    "type": "primary",
                    "action": _open_rest_app_action(
                        thread_id=thread.thread_id,
                        mode="reply",
                        title="Ответить",
                    ),
                },
            }
        },
    }


def build_layout(thread) -> dict:
    return next(_layout_variants(thread))


def _activity_type_id() -> int | None:
    value = getattr(settings, "EMAIL_ACTIVITY_TYPE_ID", None)
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _token_bitrix_user_id(token) -> int | None:
    try:
        uid = getattr(getattr(token, "user", None), "bitrix_id", None)
        return int(uid) if uid is not None else None
    except Exception:
        return None


def ensure_smartprocess_item(thread, *, title: str):
    token = _get_admin_token()
    if not token:
        raise RuntimeError("No active admin BitrixUserToken found")

    entity_type_id = _get_sp_entity_type_id(thread)

    if thread.smart_process_item_id:
        return thread.smart_process_item_id

    resp = token.call_api_method(
        "crm.item.add",
        {
            "entityTypeId": entity_type_id,
            "fields": {
                "TITLE": title[:255],
            },
        },
    )

    item_id = resp.get("result", {}).get("item", {}).get("id")
    if not item_id:
        raise RuntimeError(f"crm.item.add did not return item id: {resp}")

    thread.smart_process_entity_type_id = entity_type_id
    thread.smart_process_item_id = int(item_id)
    thread.save(update_fields=["smart_process_entity_type_id", "smart_process_item_id", "updated_at"])
    return thread.smart_process_item_id


def ensure_activity(thread):
    token = _get_admin_token()
    if not token:
        raise RuntimeError("No active admin BitrixUserToken found")

    entity_type_id = _get_sp_entity_type_id(thread)

    if thread.activity_id:
        return thread.activity_id

    params = {
        "ownerTypeId": _get_activity_owner_type_id(entity_type_id),
        "ownerId": int(thread.smart_process_item_id),
        "fields": {},
        "settings": {},
        "layout": build_layout(thread),
    }

    type_id = _activity_type_id()
    if type_id is not None:
        params["typeId"] = int(type_id)

    bitrix_user_id = _token_bitrix_user_id(token)
    if bitrix_user_id is not None:
        params["authorId"] = bitrix_user_id
        params["responsibleId"] = bitrix_user_id

    resp = token.call_api_method("crm.activity.configurable.add", params)

    activity_id = resp.get("result", {}).get("activity", {}).get("id") or resp.get("result", {}).get("id")
    if not activity_id:
        raise RuntimeError(f"crm.activity.configurable.add did not return activity id: {resp}")

    thread.activity_id = int(activity_id)
    thread.save(update_fields=["activity_id", "updated_at"])
    return thread.activity_id


def update_activity(thread):
    token = _get_admin_token()
    if not token:
        raise RuntimeError("No active admin BitrixUserToken found")

    if not thread.activity_id:
        raise ValueError("thread.activity_id is missing")

    token.call_api_method(
        "crm.activity.configurable.update",
        {
            "id": int(thread.activity_id),
            "fields": {},
            "settings": {},
            "layout": build_layout(thread),
        },
    )


def touch_thread_aggregates(thread, *, sender: str, subject: str, message_datetime):
    thread.last_message_date = message_datetime
    thread.messages_count = thread.messages.count()
    thread.last_sender = sender[:255]
    thread.last_subject = subject[:255]
    thread.updated_at = timezone.now()
    thread.save(
        update_fields=[
            "last_message_date",
            "messages_count",
            "last_sender",
            "last_subject",
            "updated_at",
        ]
    )
