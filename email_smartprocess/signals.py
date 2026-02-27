from django.dispatch import receiver
from django_mailbox.signals import message_received

from email_smartprocess.services.ingest import ingest_email, parse_message_datetime


@receiver(message_received)
def on_message_received(sender, message, **kwargs):
    email_obj = message.get_email_object()

    sender_header = (message.from_header or "")
    subject = (message.subject or "")
    message_datetime = parse_message_datetime(email_obj, message.processed)

    ingest_email(
        email_obj=email_obj,
        sender=sender_header,
        subject=subject,
        body_text=message.text or "",
        body_html=message.html or "",
        message_datetime=message_datetime,
        message_id_fallback=f"db:{message.pk}",
    )

