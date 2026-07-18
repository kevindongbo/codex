from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import StockLedger


@receiver(post_save, sender=StockLedger)
def queue_replenishment_ai_after_stock_change(sender, instance, created, **kwargs):
    if not created or instance.on_hand_delta == 0:
        return
    from .replenishment_automation import schedule_replenishment_ai_analysis
    transaction.on_commit(lambda: schedule_replenishment_ai_analysis(
        organization=instance.organization, warehouse=instance.warehouse, sku_id=instance.sku_id,
        reason=instance.event_type,
    ))
