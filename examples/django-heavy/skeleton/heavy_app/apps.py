from django.apps import AppConfig


class HeavyAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "heavy_app"
    verbose_name = "HIO-001 Heavy App (50+ Models)"
