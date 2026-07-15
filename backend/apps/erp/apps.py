from django.apps import AppConfig


class ErpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.erp"
    verbose_name = "东铂跨境运营管理系统"

    def ready(self):
        from .sync import register_sync_signals

        register_sync_signals()
