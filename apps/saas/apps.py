from django.apps import AppConfig


class SaasConfig(AppConfig):
    """The vendor's side: customers, their contracts and what they paid. Never patient data."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.saas"
    verbose_name = "Platform"
