import re


_MESSAGE_ID_RE = re.compile(r"<([^>]+)>")


def _get_header(email_obj, *names: str) -> str:
    for name in names:
        try:
            value = email_obj.get(name)
        except Exception:
            value = None
        if value:
            return value
    return ""


def normalize_message_id(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    m = _MESSAGE_ID_RE.search(value)
    if m:
        return m.group(1)
    return value


def compute_thread_id(email_obj) -> str:
    references = _get_header(email_obj, "references", "References")
    if references:
        parts = [p for p in references.split() if p]
        if parts:
            return normalize_message_id(parts[0])

    in_reply_to = _get_header(email_obj, "in-reply-to", "In-Reply-To")
    if in_reply_to:
        return normalize_message_id(in_reply_to)

    message_id = _get_header(email_obj, "message-id", "Message-ID")
    return normalize_message_id(message_id) or "unknown"
