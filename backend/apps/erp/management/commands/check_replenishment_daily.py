from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.erp.models import ReplenishmentSettings, SKUReplenishmentProfile
from apps.erp.replenishment import ReplenishmentPolicy, build_replenishment_forecast


class Command(BaseCommand):
    help = "Run the daily V3 replenishment rule check without creating purchase orders."

    def handle(self, *args, **options):
        checked = 0
        for profile in SKUReplenishmentProfile.objects.select_related("sku__product", "sku__product__default_supplier", "primary_warehouse").exclude(primary_warehouse=None):
            if not profile.sku.active or profile.sku.product.status != "active":
                continue
            settings, _ = ReplenishmentSettings.objects.get_or_create(organization=profile.organization)
            weights = (
                profile.velocity_weight_3, profile.velocity_weight_7,
                profile.velocity_weight_15, profile.velocity_weight_30,
            ) if all(value is not None for value in (
                profile.velocity_weight_3, profile.velocity_weight_7,
                profile.velocity_weight_15, profile.velocity_weight_30,
            )) else (
                settings.velocity_weight_3, settings.velocity_weight_7,
                settings.velocity_weight_15, settings.velocity_weight_30,
            )
            policy = ReplenishmentPolicy(
                target_days=Decimal(settings.target_days),
                coverage_days=profile.target_coverage_days,
                moq=profile.min_order_qty,
                pack_size=profile.pack_size,
                manual_lead_days=Decimal(profile.manual_lead_time_days or settings.default_lead_time_days),
                safety_stock_units=profile.sku.safety_stock,
            )
            build_replenishment_forecast(
                organization=profile.organization, sku=profile.sku,
                warehouse=profile.primary_warehouse,
                supplier=profile.sku.product.default_supplier,
                policy=policy, weights=weights,
            )
            checked += 1
        self.stdout.write(self.style.SUCCESS(f"checked={checked}"))
