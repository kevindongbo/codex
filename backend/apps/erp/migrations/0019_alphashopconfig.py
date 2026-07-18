import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0018_uploadedmediaasset"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AlphaShopConfig",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("access_key_encrypted", models.TextField(blank=True)),
                ("secret_key_encrypted", models.TextField(blank=True)),
                ("api_base_url", models.URLField(default="https://api.alphashop.cn", max_length=1000)),
                ("enabled", models.BooleanField(default=True)),
                ("last_configured_at", models.DateTimeField(blank=True, null=True)),
                ("configured_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="configured_alphashop_connections", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
            ],
            options={
                "verbose_name": "AlphaShop 选品接口配置",
                "verbose_name_plural": "AlphaShop 选品接口配置",
            },
        ),
        migrations.AddConstraint(
            model_name="alphashopconfig",
            constraint=models.UniqueConstraint(fields=("organization",), name="uniq_alphashop_config_org"),
        ),
    ]
