"""Durable, multi-source MYR exchange-rate snapshots."""

import json
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.db import transaction
from django.utils import timezone

from .models import ExchangeRateSnapshot


SOURCES = (
    ("European Central Bank", "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", "ecb"),
    ("Frankfurter", "https://api.frankfurter.app/latest?from=MYR&to=CNY,USD", "frankfurter"),
    ("Open ER API", "https://open.er-api.com/v6/latest/MYR", "open_er"),
)


def _decimal(value):
    return Decimal(str(value))


def _parse_ecb(payload):
    root = ElementTree.fromstring(payload)
    cube = next((node for node in root.iter() if node.tag.endswith("Cube") and node.attrib.get("time")), None)
    if cube is None:
        raise ValueError("missing dated rate table")
    rates = {node.attrib.get("currency"): _decimal(node.attrib["rate"]) for node in cube if node.attrib.get("currency")}
    return date.fromisoformat(cube.attrib["time"]), rates["CNY"] / rates["MYR"], rates["USD"] / rates["MYR"]


def _parse_json(payload, adapter):
    data = json.loads(payload.decode("utf-8"))
    if adapter == "frankfurter":
        rates = data["rates"]
        return date.fromisoformat(data["date"]), _decimal(rates["CNY"]), _decimal(rates["USD"])
    rates = data["rates"]
    raw_date = data.get("time_last_update_utc") or timezone.now().date().isoformat()
    effective = datetime.strptime(raw_date[:16], "%a, %d %b %Y").date() if "," in raw_date else date.fromisoformat(str(raw_date)[:10])
    return effective, _decimal(rates["CNY"]), _decimal(rates["USD"])


def _validate(effective, cny, usd):
    today = timezone.localdate()
    if effective > today + timedelta(days=1) or effective < today - timedelta(days=14):
        raise ValueError("rate date outside accepted window")
    if not Decimal("0.1") <= cny <= Decimal("10"):
        raise ValueError("MYR/CNY outside accepted range")
    if not Decimal("0.01") <= usd <= Decimal("2"):
        raise ValueError("MYR/USD outside accepted range")
    precision = Decimal("0.000001")
    return cny.quantize(precision), usd.quantize(precision)


@transaction.atomic
def save_snapshot(*, organization, effective_date, cny, usd, source, source_url, summary="", manual=False):
    cny, usd = _validate(effective_date, cny, usd)
    ExchangeRateSnapshot.objects.select_for_update().filter(organization=organization, is_current=True).update(is_current=False)
    return ExchangeRateSnapshot.objects.create(
        organization=organization, effective_date=effective_date, fetched_at=timezone.now(),
        myr_cny=cny, myr_usd=usd, source=source, source_url=source_url,
        validation_status="manual" if manual else "valid", response_summary=summary[:500], is_current=True,
    )


def refresh_snapshot(organization, *, respect_manual=False):
    if respect_manual and ExchangeRateSnapshot.objects.filter(
        organization=organization, is_current=True, validation_status="manual"
    ).exists():
        return ExchangeRateSnapshot.objects.filter(organization=organization, is_current=True).first(), ["manual override preserved"]
    failures = []
    for source, url, adapter in SOURCES:
        for attempt in range(2):
            try:
                request = Request(url, headers={"Accept": "application/json, application/xml", "User-Agent": "DongboERP/1.0"})
                with urlopen(request, timeout=6) as response:
                    payload = response.read()
                effective, cny, usd = _parse_ecb(payload) if adapter == "ecb" else _parse_json(payload, adapter)
                return save_snapshot(
                    organization=organization, effective_date=effective, cny=cny, usd=usd,
                    source=source, source_url=url,
                    summary=(
                        f"validated {len(payload)} byte response"
                        + (f"; earlier failures: {'; '.join(failures)}" if failures else "")
                    ),
                ), failures
            except Exception as exc:
                failures.append(f"{source} attempt {attempt + 1}: {type(exc).__name__}")
                if attempt == 0:
                    time.sleep(0.05)
    return None, failures


def record_refresh_failure(snapshot, failures):
    """Persist a safe failure summary without replacing the last valid rates."""
    if snapshot is None:
        return
    snapshot.used_history_fallback = True
    snapshot.response_summary = ("; ".join(failures))[:500]
    snapshot.save(update_fields=["used_history_fallback", "response_summary", "updated_at"])


def snapshot_payload(snapshot, *, fallback=False, failures=None):
    used_fallback = bool(fallback or snapshot.used_history_fallback)
    return {
        "id": str(snapshot.pk), "date": str(snapshot.effective_date), "fetched_at": snapshot.fetched_at,
        "cny_per_myr": str(snapshot.myr_cny), "usd_per_myr": str(snapshot.myr_usd),
        "source": snapshot.source, "source_url": snapshot.source_url,
        "stale": used_fallback, "used_history_fallback": used_fallback,
        "validation_status": snapshot.validation_status, "failures": failures or [],
    }
