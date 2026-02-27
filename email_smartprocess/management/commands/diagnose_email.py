from django.core.management.base import BaseCommand

from email_smartprocess.services.gmail_imap import safe_uri_for_log


class Command(BaseCommand):
    help = "Diagnose email_smartprocess integration state"

    def handle(self, *args, **options):
        from django.conf import settings

        self.stdout.write("== Settings ==")
        self.stdout.write(f"DEBUG={settings.DEBUG}")
        self.stdout.write(f"EMAIL_SP_ENTITY_TYPE_ID={getattr(settings, 'EMAIL_SP_ENTITY_TYPE_ID', None)}")
        self.stdout.write(f"APP_DOMAIN={getattr(settings, 'APP_DOMAIN', None) or getattr(settings, 'DOMAIN', None)}")
        self.stdout.write(f"EMAIL_MAILBOX_LOOKBACK_HOURS={getattr(settings, 'EMAIL_MAILBOX_LOOKBACK_HOURS', None)}")
        self.stdout.write(f"EMAIL_GMAIL_FAST={getattr(settings, 'EMAIL_GMAIL_FAST', True)}")
        self.stdout.write(f"EMAIL_GMAIL_RAW_QUERY={getattr(settings, 'EMAIL_GMAIL_RAW_QUERY', None)}")

        self.stdout.write("\n== SMTP configured ==")
        smtp_ok = all(
            getattr(settings, k, None)
            for k in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_SMTP_USER", "EMAIL_SMTP_PASSWORD")
        )
        self.stdout.write(str(smtp_ok))

        self.stdout.write("\n== django_mailbox ==")
        from django_mailbox.models import Mailbox, Message

        self.stdout.write(f"Mailboxes total={Mailbox.objects.count()} active={Mailbox.active_mailboxes.count()}")
        for m in Mailbox.objects.all().order_by("id"):
            uri_str = safe_uri_for_log(m.uri) if m.uri else "EMPTY"
            self.stdout.write(
                f"- Mailbox {m.id}: name={m.name} active={m.active} last_polling={m.last_polling} uri={uri_str}"
            )
        self.stdout.write(f"Messages total={Message.objects.count()}")

        self.stdout.write("\n== email_smartprocess ==")
        from email_smartprocess.models import EmailMessage, EmailThread

        self.stdout.write(f"Threads total={EmailThread.objects.count()} Messages total={EmailMessage.objects.count()}")
        last_thread = EmailThread.objects.order_by("-updated_at").first()
        if last_thread:
            self.stdout.write(
                f"Last thread: {last_thread.thread_id} sp_item={last_thread.smart_process_item_id} "
                f"activity={last_thread.activity_id} updated_at={last_thread.updated_at}"
            )

        self.stdout.write("\n== Bitrix token ==")
        try:
            from integration_utils.bitrix24.models import BitrixUserToken

            tok = BitrixUserToken.get_admin_token()
            self.stdout.write(f"Admin token present={bool(tok)}")
            if tok:
                self.stdout.write(f"Token id={tok.id} domain={tok.domain} active={tok.is_active}")
        except Exception as exc:
            self.stdout.write(f"Cannot check BitrixUserToken: {exc!r}")

