from django.contrib import admin

from .models import EmailThread, EmailMessage


@admin.register(EmailThread)
class EmailThreadAdmin(admin.ModelAdmin):
    list_display = (
        "thread_id",
        "smart_process_entity_type_id",
        "smart_process_item_id",
        "activity_id",
        "messages_count",
        "last_message_date",
    )
    search_fields = ("thread_id",)


@admin.register(EmailMessage)
class EmailMessageAdmin(admin.ModelAdmin):
    list_display = ("message_id", "thread", "sender", "subject", "created_at")
    search_fields = ("message_id", "sender", "subject")
    raw_id_fields = ("thread",)
