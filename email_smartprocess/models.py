from django.db import models


class EmailThread(models.Model):
    thread_id = models.CharField(max_length=255, unique=True)

    smart_process_entity_type_id = models.IntegerField(null=True, blank=True)
    smart_process_item_id = models.IntegerField(null=True, blank=True)
    activity_id = models.IntegerField(null=True, blank=True)

    last_message_date = models.DateTimeField(null=True, blank=True)
    messages_count = models.PositiveIntegerField(default=0)
    last_sender = models.CharField(max_length=255, blank=True, default="")
    last_subject = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.thread_id


class EmailMessage(models.Model):
    thread = models.ForeignKey(EmailThread, on_delete=models.CASCADE, related_name="messages")

    message_id = models.CharField(max_length=255, unique=True)
    sender = models.CharField(max_length=255, blank=True, default="")
    subject = models.CharField(max_length=255, blank=True, default="")
    body_text = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")

    created_at = models.DateTimeField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.message_id
