from decimal import Decimal
import uuid

from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_replenishment_profiles(apps, schema_editor):
    SKU = apps.get_model("erp", "SKU")
    Profile = apps.get_model("erp", "SKUReplenishmentProfile")
    LegacyPolicy = apps.get_model("erp", "ReplenishmentPolicy")
    for sku in SKU.objects.all().iterator():
        policies = list(LegacyPolicy.objects.filter(organization_id=sku.organization_id, sku_id=sku.pk).order_by("-updated_at", "id"))
        chosen = policies[0] if policies else None
        Profile.objects.get_or_create(
            sku_id=sku.pk,
            defaults={
                "organization_id": sku.organization_id,
                "primary_warehouse_id": chosen.warehouse_id if chosen else None,
                "target_coverage_days": chosen.target_days if chosen else 30,
                "manual_lead_time_days": chosen.lead_time_override if chosen else None,
                "min_order_qty": None if not chosen or chosen.min_order_qty == Decimal("1") else chosen.min_order_qty,
                "pack_size": None if not chosen or chosen.pack_size == Decimal("1") else chosen.pack_size,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("erp", "0034_creator_attribution_unattributed")]

    operations = [
        migrations.CreateModel(
            name="SKUReplenishmentProfile",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False, editable=False, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("velocity_weight_3", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("velocity_weight_7", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("velocity_weight_15", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("velocity_weight_30", models.DecimalField(blank=True, decimal_places=3, max_digits=5, null=True)),
                ("target_coverage_days", models.PositiveIntegerField(blank=True, default=30, null=True)),
                ("manual_lead_time_days", models.PositiveIntegerField(blank=True, null=True)),
                ("min_order_qty", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("pack_size", models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
                ("primary_warehouse", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="primary_replenishment_skus", to="erp.warehouse")),
                ("sku", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="replenishment_profile", to="erp.sku")),
            ],
        ),
        migrations.AddConstraint(model_name="skureplenishmentprofile", constraint=models.CheckConstraint(condition=models.Q(("target_coverage_days__isnull", True), ("target_coverage_days__gt", 0), _connector="OR"), name="sku_replenishment_coverage_positive")),
        migrations.AddConstraint(model_name="skureplenishmentprofile", constraint=models.CheckConstraint(condition=models.Q(("min_order_qty__isnull", True), ("min_order_qty__gt", 0), _connector="OR"), name="sku_replenishment_moq_positive")),
        migrations.AddConstraint(model_name="skureplenishmentprofile", constraint=models.CheckConstraint(condition=models.Q(("pack_size__isnull", True), ("pack_size__gt", 0), _connector="OR"), name="sku_replenishment_pack_positive")),
        migrations.RunPython(migrate_legacy_replenishment_profiles, migrations.RunPython.noop),
    ]
