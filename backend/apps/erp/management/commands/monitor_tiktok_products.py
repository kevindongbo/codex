from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from apps.erp.models import CompetitorProduct
from apps.erp.services import collect_tiktok_competitor_snapshot
from apps.erp.tiktok_monitoring import TikTokMonitoringError, configured_providers


class Command(BaseCommand):
    help = "Collect buyer-visible TikTok Shop snapshots for active MY competitors."

    def add_arguments(self, parser):
        parser.add_argument("--market", default=settings.TIKTOK_MONITOR_DEFAULT_MARKET)
        parser.add_argument("--product-id", action="append", dest="product_ids")
        parser.add_argument("--provider", choices=("auto", "tikhub", "apify"), default="auto")
        parser.add_argument("--min-age-minutes", type=int, default=None)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        market = str(options["market"] or "MY").strip().upper()
        if market != "MY":
            raise CommandError("当前定时采集只开放马来西亚 MY 市场")
        minimum_age = options["min_age_minutes"]
        if minimum_age is None:
            minimum_age = settings.TIKTOK_MONITOR_INTERVAL_MINUTES
        if minimum_age < 0:
            raise CommandError("--min-age-minutes 不能小于 0")

        queryset = CompetitorProduct.objects.filter(
            active=True,
            linked_product__isnull=True,
            market__iexact=market,
        ).filter(Q(platform__iexact="tiktok_shop") | Q(url__icontains="tiktok.com"))
        if options["product_ids"]:
            queryset = queryset.filter(pk__in=options["product_ids"])
        queryset = queryset.order_by("organization_id", "id")
        if options["limit"] > 0:
            queryset = queryset[: options["limit"]]
        products = list(queryset)

        if options["dry_run"]:
            for product in products:
                self.stdout.write(f"TARGET {product.pk} {product.name or '(未命名)'} {product.url}")
            self.stdout.write(self.style.SUCCESS(f"DRY RUN：符合条件 {len(products)} 个竞品"))
            return
        try:
            configured_providers(options["provider"])
        except TikTokMonitoringError as exc:
            raise CommandError(str(exc)) from exc

        cutoff = timezone.now() - timedelta(minutes=minimum_age)
        succeeded = skipped = failed = 0
        for product in products:
            latest = product.snapshots.order_by("-captured_at").only("captured_at").first()
            if not options["force"] and latest is not None and latest.captured_at > cutoff:
                skipped += 1
                self.stdout.write(f"SKIP {product.pk} 最近一次采集仍在间隔内")
                continue
            try:
                snapshot = collect_tiktok_competitor_snapshot(
                    product=product,
                    provider=options["provider"],
                )
            except Exception as exc:  # continue collecting other products; strict mode fails at the end
                failed += 1
                self.stderr.write(self.style.ERROR(f"ERROR {product.pk} {product.name or '(未命名)'}：{exc}"))
                continue
            succeeded += 1
            provider = (snapshot.raw.get("monitoring") or {}).get("provider", "unknown")
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK {product.pk} provider={provider} sold={snapshot.sold_count} price={snapshot.price}"
                )
            )

        summary = f"完成：成功 {succeeded}，跳过 {skipped}，失败 {failed}，候选 {len(products)}"
        if failed and options["strict"]:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary) if not failed else self.style.WARNING(summary))
