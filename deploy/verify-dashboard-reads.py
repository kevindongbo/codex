"""Authenticated GET smoke checks. Prints paths/counts, never tokens or row values."""
import json
import os
import sys
import urllib.request

sys.path.insert(0, "backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django
django.setup()
from django.contrib.auth import get_user_model
from apps.erp.authentication import issue_refresh


def verify():
    owner = get_user_model().objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
    if owner is None:
        raise RuntimeError("No active primary account for authenticated checks")
    token = str(issue_refresh(owner).access_token)
    headers = {"Host": "dongbokeji.com", "X-Forwarded-Proto": "https", "Authorization": "Bearer " + token}

    def read(path):
        request = urllib.request.Request("http://127.0.0.1:8000/api" + path, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            value = json.load(response)
            if isinstance(value, list):
                print(path + ": HTTP 200; rows=" + str(len(value)))
            elif isinstance(value, dict):
                print(path + ": HTTP 200" + ("; count=" + str(value["count"]) if "count" in value else ""))
            else:
                raise RuntimeError("Unexpected response shape: " + path)
            return value

    warehouses = read("/warehouses/")
    rows = warehouses if isinstance(warehouses, list) else warehouses.get("results", [])
    warehouse = next((w for w in rows if w.get("active")), None)
    if warehouse is None:
        raise RuntimeError("No active warehouse; dashboard cannot initialize")
    paths = ["/products/", "/suppliers/", "/purchase-orders/", "/stock-balances/", "/stock-ledger/",
             "/orders/", "/shipments/", "/returns/", "/competitors/", "/competitor-snapshots/",
             "/stock-transfers/", "/replenishment-policies/",
             "/replenishment/recommendations/?warehouse=" + str(warehouse["id"]),
             "/stores/", "/store-products/", "/skus/profit-summary/", "/profit-calculator/config/", "/sync/version/"]
    for path in paths:
        read(path)
    print("AUTHENTICATED DASHBOARD READS VERIFIED; GET requests only; no paid API calls")


if __name__ == "__main__":
    verify()
