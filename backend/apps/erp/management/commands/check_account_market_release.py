from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Q
from django.db.migrations.executor import MigrationExecutor
from apps.erp.models import AccountLifecycleRequest, AccountSecurityState, Membership, MarketSnapshot, MarketStrategy, MarketWorkspace, SKUMarketProfile, StoreProduct
from apps.erp.market_calculator import CalculationInput, calculate, digest


class Command(BaseCommand):
    help = "只读核验账号归档、多国迁移、权限与计算引擎；不调用外部服务。"

    def handle(self, **options):
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise CommandError("数据库还有待执行的迁移")
        if Membership.objects.filter(employment_status="departed").filter(Q(active=True) | Q(user__is_active=True)).exists():
            raise CommandError("离职人员仍启用，停止发布")
        if AccountSecurityState.objects.filter(requires_password_reset=True, user__is_active=True).exists():
            raise CommandError("恢复人员未重置密码却已启用")
        if StoreProduct.objects.filter(country__in=["US", "MX"], sale_price_myr__isnull=False).exists():
            raise CommandError("US/MX售价错误写入MYR兼容字段")
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                for model, privileges in [(AccountSecurityState, ["SELECT", "INSERT", "UPDATE"]),
                    (AccountLifecycleRequest, ["SELECT", "INSERT"]), (MarketSnapshot, ["SELECT", "INSERT"]),
                    (MarketStrategy, ["SELECT", "INSERT", "UPDATE", "DELETE"]),
                    (MarketWorkspace, ["SELECT", "INSERT", "UPDATE"]), (SKUMarketProfile, ["SELECT", "INSERT", "UPDATE"])]:
                    for privilege in privileges:
                        cursor.execute("SELECT has_table_privilege(current_user, %s, %s)", [model._meta.db_table, privilege])
                        if cursor.fetchone()[0] is not True:
                            raise CommandError("新增功能表权限不足：" + model._meta.db_table + " " + privilege)
        from types import SimpleNamespace
        serializer = CalculationInput(data={"schema_version": 2, "country": "US", "currency": "USD", "seller_program": "synthetic",
            "fulfillment_service": "seller_shipping", "fees_confirmed": True,
            "items": [{"client_item_id": "a", "sku_name": "synthetic", "category_mapping_id": "US:home_security", "quantity": 1,
                "unit_price": "100", "product_cost_cny": "140", "first_leg_cost_cny": "21", "affiliate_rate": "10", "commission_rate": "6",
                "commission_source": "synthetic", "other_cost": "0", "other_cost_source": "synthetic", "tax_expense": "0", "tax_withholding": "0", "tax_source": "synthetic"}],
            "packages": [{"client_package_id": "p", "items": [{"client_item_id": "a", "quantity": 1}], "weight": {"value": "500", "unit": "g"},
                "dimensions": {"length": "20", "width": "15", "height": "10", "unit": "cm"}, "battery_profile": "plug_in_no_battery"}]})
        serializer.is_valid(raise_exception=True)
        rates = SimpleNamespace(payload={"cny_per_base": "7", "usd_per_base": "1"}, content_hash="synthetic")
        quote = SimpleNamespace(payload={"lines": [{"amount": "8"}], "payment_channel": "offline", "source": "synthetic"}, content_hash="synthetic")
        result = calculate(serializer.validated_data, rates, quote)
        if (result["gross_profit"], result["break_even_roi"], result["platform_payout"]) != ("53.00", "1.89", "84.00"):
            raise CommandError("多国引擎合成样例不一致")
        self.stdout.write("ACCOUNT / MARKET MIGRATIONS, INVARIANTS, PRIVILEGES AND SYNTHETIC CALCULATION OK")
        self.stdout.write("Read-only verification; no account mutations, external quotes or paid API calls. Actual shop acceptance remains required.")
