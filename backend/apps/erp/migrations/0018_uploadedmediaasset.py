import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0017_erp_operations_platform"),
    ]

    operations = [
        migrations.CreateModel(
            name="UploadedMediaAsset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("file", models.FileField(upload_to="organization-images/%Y/%m/%d")),
                ("original_name", models.CharField(blank=True, max_length=255)),
                ("content_type", models.CharField(blank=True, max_length=100)),
                ("size", models.PositiveIntegerField(default=0)),
                ("sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="erp.organization")),
            ],
        ),
        migrations.AddIndex(
            model_name="uploadedmediaasset",
            index=models.Index(fields=["organization", "created_at"], name="erp_uploade_organiz_69548a_idx"),
        ),
    ]
