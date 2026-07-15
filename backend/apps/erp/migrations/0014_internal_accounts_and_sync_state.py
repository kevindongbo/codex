# Generated manually for the internal single-organization account upgrade.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0013_chinese_admin_labels"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="permissions",
            field=models.JSONField(blank=True, default=list, verbose_name="权限清单"),
        ),
        migrations.CreateModel(
            name="OwnerEmailChallenge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("purpose", models.CharField(choices=[("login", "登录验证"), ("password_change", "修改密码"), ("password_reset", "找回密码")], max_length=32)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="owner_email_challenges", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "主账号邮箱验证码", "verbose_name_plural": "主账号邮箱验证码", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="OrganizationSyncState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveBigIntegerField(default=1, verbose_name="数据版本")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("organization", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sync_state", to="erp.organization", verbose_name="所属组织")),
            ],
            options={"verbose_name": "数据同步状态", "verbose_name_plural": "数据同步状态"},
        ),
    ]
