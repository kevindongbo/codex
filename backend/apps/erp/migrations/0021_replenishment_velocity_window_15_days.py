from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("erp", "0020_tiktok_shop_connections_per_shop"),
    ]

    operations = [
        migrations.RenameField(
            model_name="replenishmentsettings",
            old_name="velocity_weight_14",
            new_name="velocity_weight_15",
        ),
        migrations.AlterField(
            model_name="replenishmentsettings",
            name="velocity_weight_15",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.300"),
                max_digits=5,
                verbose_name="近 15 天权重",
            ),
        ),
        migrations.AddField(
            model_name="replenishmentsettings",
            name="safety_margin_ratio",
            field=models.DecimalField(
                decimal_places=3,
                default=Decimal("0.200"),
                max_digits=5,
                verbose_name="建议补货安全余量比例",
            ),
        ),
        migrations.AddConstraint(
            model_name="replenishmentsettings",
            constraint=models.CheckConstraint(
                condition=models.Q(safety_margin_ratio__gte=0) & models.Q(safety_margin_ratio__lte=1),
                name="replenishment_settings_margin_between_zero_and_one",
            ),
        ),
    ]
