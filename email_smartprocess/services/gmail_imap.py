from __future__ import annotations

import email
import imaplib
from email.header import decode_header, make_header
from urllib.parse import parse_qs, unquote, urlparse


class GmailImapError(RuntimeError):
    pass


def parse_imap_uri(uri: str):
    p = urlparse(uri)
    if not p.scheme.startswith("imap"):
        raise GmailImapError(f"Unsupported uri scheme: {p.scheme!r}")

    host = p.hostname
    if not host:
        raise GmailImapError("IMAP host is missing in uri")

    use_ssl = "ssl" in p.scheme
    port = p.port or (993 if use_ssl else 143)

    username = unquote(p.username or "")
    password = unquote(p.password or "")
    if not username or not password:
        raise GmailImapError("IMAP username/password missing in uri")

    qs = parse_qs(p.query or "")
    folder = (qs.get("folder") or [None])[0] or "INBOX"

    return {
        "scheme": p.scheme,
        "host": host,
        "port": int(port),
        "use_ssl": bool(use_ssl),
        "username": username,
        "password": password,
        "folder": folder,
    }


def safe_uri_for_log(uri: str) -> str:
    try:
        info = parse_imap_uri(uri)
        return f"{info['scheme']}://{info['username']}@{info['host']}:{info['port']}?folder={info['folder']}"
    except Exception:
        return "<invalid uri>"


def _decode_header(value: str) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def extract_bodies(msg) -> tuple[str, str]:
    text_parts: list[str] = []
    html_parts: list[str] = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue

        ctype = (part.get_content_type() or "").lower()
        if ctype not in ("text/plain", "text/html"):
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            continue

        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except Exception:
            decoded = payload.decode("utf-8", errors="replace")

        if ctype == "text/plain":
            text_parts.append(decoded)
        else:
            html_parts.append(decoded)

    return ("\n\n".join(text_parts)).strip(), ("\n\n".join(html_parts)).strip()


def fetch_recent_gmail_messages(*, uri: str, raw_query: str):
    info = parse_imap_uri(uri)

    conn = imaplib.IMAP4_SSL(info["host"], info["port"]) if info["use_ssl"] else imaplib.IMAP4(info["host"], info["port"])
    try:
        try:
            conn.login(info["username"], info["password"])
        except Exception as exc:
            raise GmailImapError(f"IMAP login failed: {exc!r}") from exc

        status, _ = conn.select(info["folder"])
        if status != "OK":
            raise GmailImapError(f"Cannot select folder {info['folder']!r}")

        # SEARCH signature: (charset, *criteria). For Gmail we use X-GM-RAW extension.
        status, data = conn.uid("SEARCH", None, "X-GM-RAW", raw_query)
        if status != "OK":
            raise GmailImapError(f"X-GM-RAW SEARCH failed for query {raw_query!r}")

        raw = (data[0] or b"").strip()
        if not raw:
            return []

        uids = [u for u in raw.split() if u]
        out = []
        for uid in uids:
            status, parts = conn.uid("FETCH", uid, "(RFC822)")
            if status != "OK":
                continue

            raw_bytes = None
            for part in parts:
                if isinstance(part, tuple) and part and part[1]:
                    raw_bytes = part[1]
                    break
            if not raw_bytes:
                continue

            msg = email.message_from_bytes(raw_bytes)
            body_text, body_html = extract_bodies(msg)
            out.append(
                {
                    "uid": uid.decode("ascii", errors="ignore"),
                    "email_obj": msg,
                    "from": _decode_header(msg.get("From", "")),
                    "subject": _decode_header(msg.get("Subject", "")),
                    "body_text": body_text,
                    "body_html": body_html,
                }
            )

        return out
    finally:
        try:
            conn.logout()
        except Exception:
            pass
