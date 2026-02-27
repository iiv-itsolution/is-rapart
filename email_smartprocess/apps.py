from django.apps import AppConfig


class EmailSmartprocessConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "email_smartprocess"

    def ready(self):
        from . import signals  # noqa: F401
