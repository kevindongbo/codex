from django.db import migrations


def forwards(apps, schema_editor):
    Store = apps.get_model("erp", "OwnStore")
    Listing = apps.get_model("erp", "StoreProduct")
    aliases = {"MY": ("MY", "MYR"), "马来西亚": ("MY", "MYR"), "Malaysia": ("MY", "MYR"),
               "US": ("US", "USD"), "美国": ("US", "USD"), "USA": ("US", "USD"),
               "MX": ("MX", "MXN"), "墨西哥": ("MX", "MXN"), "Mexico": ("MX", "MXN")}
    alias = schema_editor.connection.alias
    for s in Store.objects.using(alias).all().iterator():
        match = aliases.get(s.market.strip())
        # An existing MYR field proves the stored amount's denomination, not
        # that a free-text US/MX store was configured correctly.
        has_legacy = Listing.objects.using(alias).filter(store=s, sale_price_myr__isnull=False).exists()
        if match and not (has_legacy and match[0] != "MY"):
            Store.objects.using(alias).filter(pk=s.pk, country_code="").update(country_code=match[0], currency=match[1])
    for l in Listing.objects.using(alias).filter(price_amount__isnull=True, sale_price_myr__isnull=False).iterator():
        Listing.objects.using(alias).filter(pk=l.pk, price_amount__isnull=True).update(
            price_amount=l.sale_price_myr, country="MY", currency="MYR")


def preserve(apps, schema_editor):
    # Intentional logical rollback: preserve monetary evidence and auth state.
    pass


class Migration(migrations.Migration):
    dependencies = [("erp", "0039_account_departure_market_v2")]
    operations = [migrations.RunPython(forwards, preserve)]
