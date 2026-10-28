"""Release helper: safe fingerprints, scoped grants, no credential output.

Run from the checkout with the existing server environment loaded. Inventory
works against both 0038 and 0040 and never reads password/token columns.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd() / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.db import connection

QUERIES = {
    "products": "SELECT id, organization_id, name, status FROM erp_product ORDER BY id",
    "skus": "SELECT id, organization_id, product_id, code, cost, currency, active FROM erp_sku ORDER BY id",
    "stores": "SELECT id, organization_id, name, platform_code, market, is_active FROM erp_ownstore ORDER BY id",
    "users": "SELECT id, is_active FROM auth_user ORDER BY id",
    "members": "SELECT id, user_id, role, active FROM erp_membership ORDER BY id",
    "prices": "SELECT id, store_id, sku_id, sale_price_myr, commission_override_percent FROM erp_storeproduct ORDER BY id",
    "stock": "SELECT id, warehouse_id, sku_id, on_hand, reserved, in_transit, purchased_pending_shipment FROM erp_stockbalance ORDER BY id",
    "ledger": "SELECT id, warehouse_id, sku_id, on_hand_delta, reserved_delta, actor_id FROM erp_stockledger ORDER BY id",
    "purchases": "SELECT id, purchaser_id, status FROM erp_purchaseorder ORDER BY id",
    "profit_history": "SELECT id, plan_id, version_number, input_snapshot, result_snapshot, exchange_rate_snapshot FROM erp_profitplanversion ORDER BY id",
}
PRIVILEGES = {
    "erp_accountsecuritystate": ("SELECT", "INSERT", "UPDATE"),
    "erp_accountlifecyclerequest": ("SELECT", "INSERT"),
    "erp_marketworkspace": ("SELECT", "INSERT", "UPDATE"),
    "erp_marketstrategy": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "erp_marketsnapshot": ("SELECT", "INSERT"),
    "erp_skumarketprofile": ("SELECT", "INSERT", "UPDATE"),
}


def inventory():
    value = {}
    with connection.cursor() as cursor:
        for key, query in QUERIES.items():
            h = hashlib.sha256()
            cursor.execute(query)
            count = 0
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                for row in rows:
                    h.update(json.dumps(row, sort_keys=True, default=str, separators=(",", ":")).encode() + b"\n")
                    count += 1
            value[key] = {"count": count, "hash": h.hexdigest()}
    return value


def grants():
    from psycopg import sql
    role = os.environ.get("RELEASE_DB_ROLE", "")
    if not role:
        raise RuntimeError("Missing migration role context")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        if cursor.fetchone()[0] != "postgres":
            raise RuntimeError("Scoped grants require local migration administrator")
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [role])
        if cursor.fetchone() is None:
            raise RuntimeError("Application role missing")
        for table, privileges in PRIVILEGES.items():
            cursor.execute(sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                sql.SQL(", ").join(map(sql.SQL, privileges)), sql.Identifier("public", table), sql.Identifier(role)))
    print("SCOPED NEW TABLE PRIVILEGES GRANTED; no global grants or owner changes")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "inventory":
        target = Path(sys.argv[2])
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
            json.dump(inventory(), f, sort_keys=True)
        print("PRE-MIGRATION FINGERPRINTS SAVED (no record values printed)")
    elif mode == "compare":
        before = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        if inventory() != before:
            raise RuntimeError("Historical data fingerprint changed; keep maintenance and investigate")
        print("HISTORICAL ACCOUNT / PRICE / STOCK / PURCHASE / PROFIT FINGERPRINTS MATCH")
    elif mode == "grant":
        grants()
    else:
        raise RuntimeError("Unsupported release operation")
