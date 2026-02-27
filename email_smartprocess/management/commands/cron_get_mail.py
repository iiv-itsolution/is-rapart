from __future__ import annotations

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_mailbox.models import Mailbox

from email_smartprocess.services.gmail_imap import fetch_recent_gmail_messages, safe_uri_for_log
from email_smartprocess.services.ingest import ingest_email, parse_message_datetime


class Command(BaseCommand):
    help = "Fetch mail for all active mailboxes (safe mode by default)"

    def handle(self, *args, **options):
        mailboxes = Mailbox.active_mailboxes.all()

        fetch_all = bool(getattr(settings, "EMAIL_MAILBOX_FETCH_ALL", False))
        lookback_hours = int(getattr(settings, "EMAIL_MAILBOX_LOOKBACK_HOURS", 1))

        self.stdout.write(f"Active mailboxes: {mailboxes.count()}")

        for mailbox in mailboxes:
            self.stdout.write(
                f"- Mailbox {mailbox.id}: {mailbox.name} active={mailbox.active} last_polling={mailbox.last_polling}"
            )
            try:
                if fetch_all:
                    self.stdout.write("  mode=fetch_all")
                    fetched = 0
                    for _ in mailbox.get_new_mail():
                        fetched += 1
                    mailbox.last_polling = timezone.now()
                    mailbox.save(update_fields=["last_polling"])
                    self.stdout.write(f"  fetched={fetched} last_polling={mailbox.last_polling}")
                    continue

                cutoff = mailbox.last_polling
                if not cutoff:
                    cutoff = timezone.now() - datetime.timedelta(hours=lookback_hours)

                uri = mailbox.uri or ""
                use_gmail_fast = bool(getattr(settings, "EMAIL_GMAIL_FAST", True)) and ("imap.gmail.com" in uri)

                if use_gmail_fast:
                    # For Gmail we always work with a rolling window (e.g. last hour) via X-GM-RAW.
                    # Using mailbox.last_polling as a strict cutoff breaks on frequent polls because
                    # the message "Date" header is usually earlier than the poll moment.
                    cutoff = timezone.now() - datetime.timedelta(hours=lookback_hours)
                    raw_query = getattr(settings, "EMAIL_GMAIL_RAW_QUERY", None) or f"newer_than:{lookback_hours}h"
                    self.stdout.write(f"  mode=gmail_fast uri={safe_uri_for_log(uri)} query={raw_query!r}")

                    items = fetch_recent_gmail_messages(uri=uri, raw_query=raw_query)
                    self.stdout.write(f"  gmail_uids={len(items)}")

                    ingested = 0
                    skipped = 0
                    errors = 0
                    ignored_by_cutoff = 0
                    for item in items:
                        email_obj = item["email_obj"]
                        msg_dt = parse_message_datetime(email_obj, timezone.now())
                        if msg_dt < cutoff:
                            ignored_by_cutoff += 1
                            continue

                        try:
                            thread = ingest_email(
                                email_obj=email_obj,
                                sender=item.get("from", ""),
                                subject=item.get("subject", ""),
                                body_text=item.get("body_text", ""),
                                body_html=item.get("body_html", ""),
                                message_datetime=msg_dt,
                                message_id_fallback=f"gmail:{mailbox.id}:{item.get('uid')}",
                            )
                            if thread is None:
                                skipped += 1
                            else:
                                ingested += 1
                        except Exception as exc:
                            errors += 1
                            self.stderr.write(f"  ingest ERROR uid={item.get('uid')}: {exc!r}")

                    mailbox.last_polling = timezone.now()
                    mailbox.save(update_fields=["last_polling"])
                    self.stdout.write(
                        f"  ingested={ingested} skipped={skipped} errors={errors} "
                        f"ignored_by_cutoff={ignored_by_cutoff} last_polling={mailbox.last_polling}"
                    )
                    continue

                self.stdout.write(f"  mode=since cutoff={cutoff}")

                def condition(email_obj):
                    dt = parse_message_datetime(email_obj, timezone.now())
                    return dt >= cutoff

                fetched = 0
                for _ in mailbox.get_new_mail(condition=condition):
                    fetched += 1

                mailbox.last_polling = timezone.now()
                mailbox.save(update_fields=["last_polling"])
                self.stdout.write(f"  fetched={fetched} last_polling={mailbox.last_polling}")

            except Exception as exc:
                # Do not auto-deactivate on errors: Bitrix/config issues should not kill the mailbox.
                self.stderr.write(f"  ERROR: {exc!r}")
