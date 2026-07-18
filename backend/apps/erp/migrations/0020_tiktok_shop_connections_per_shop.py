from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp", "0019_alphashopconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="tiktokshopconnection",
            name="seller_type",
            field=models.CharField(blank=True, max_length=40, verbose_name="授权主体类型"),
        ),
        migrations.AddField(
            model_name="tiktokshopconnection",
            name="shop_cipher",
            field=models.CharField(blank=True, max_length=260, verbose_name="店铺加密标识"),
        ),
        migrations.AddField(
            model_name="tiktokshopconnection",
            name="shop_name",
            field=models.CharField(blank=True, max_length=200, verbose_name="店铺名称"),
        ),
        migrations.RemoveConstraint(
            model_name="tiktokshopconnection",
            name="uniq_tiktok_connection_open_id",
        ),
        migrations.AddConstraint(
            model_name="tiktokshopconnection",
            constraint=models.UniqueConstraint(
                fields=("organization", "open_id", "shop_id"),
                name="uniq_tiktok_connection_shop",
            ),
        ),
    ]
