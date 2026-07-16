from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("erp", "0015_competitor_drafts")]

    operations = [
        migrations.AlterField(
            model_name="productimage",
            name="url",
            field=models.TextField(max_length=560000),
        ),
    ]
