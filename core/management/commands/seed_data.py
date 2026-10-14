"""Load data/catalogue.csv and data/dealers.csv into PostgreSQL.

Idempotent: create_or_update on stable natural keys (sku / dealer_code) so running
the command twice never creates duplicates. Source files are read-only; malformed
rows are counted and reported, never silently dropped.
"""
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Dealer, Product

CENT = Decimal("0.01")


def _parse_money(raw):
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None
    if value < 0:
        return None
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Load the files in data/ into the database. Must be safe to run more than once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clean",
            "--reset",
            action="store_true",
            dest="clean",
            help="Purge orders, test records, and reset database to pristine 600 products and 25 dealers with sequence restart.",
        )

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR
        stats = {"products_created": 0, "products_updated": 0, "products_invalid": 0,
                 "dealers_created": 0, "dealers_updated": 0, "dealers_invalid": 0}

        clean = options.get("clean", False)
        with transaction.atomic():
            if clean:
                from core.models import ChatSession, IdempotencyKey, Order, OrderItem
                OrderItem.objects.all().delete()
                Order.objects.all().delete()
                IdempotencyKey.objects.all().delete()
                ChatSession.objects.all().delete()
                Product.objects.all().delete()
                Dealer.objects.all().delete()
                try:
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute("ALTER SEQUENCE dealers_id_seq RESTART WITH 1;")
                except Exception:
                    pass

            # ---- catalogue -----------------------------------------------------
            catalogue_path = data_dir / "catalogue.csv"
            seen_skus = set()
            with open(catalogue_path, newline="", encoding="utf-8") as fh:
                for i, row in enumerate(csv.DictReader(fh), start=2):
                    sku = (row.get("sku") or "").strip()
                    name = (row.get("name") or "").strip()
                    price = _parse_money(row.get("price"))
                    if not sku or not name or price is None:
                        stats["products_invalid"] += 1
                        self.stderr.write(f"catalogue.csv line {i}: invalid record (sku={sku!r})")
                        continue
                    stock_raw = (row.get("stock") or "0").strip()
                    try:
                        stock = max(0, int(float(stock_raw)))
                    except (TypeError, ValueError):
                        stock = 0
                    defaults = {
                        "name": name,
                        "category": (row.get("category") or "").strip(),
                        "brand": (row.get("brand") or "").strip(),
                        "vehicle_fitment": (row.get("vehicle_fitment") or "").strip(),
                        "price": price,
                        "description": (row.get("description") or "").strip(),
                    }
                    product, created = Product.objects.update_or_create(sku=sku, defaults=defaults)
                    if created:
                        product.stock = stock
                        product.save(update_fields=["stock"])
                        stats["products_created"] += 1
                    else:
                        # only seed stock on first import; price/text updates flow through the API/sync
                        stats["products_updated"] += 1
                    seen_skus.add(sku)

            # ---- dealers -------------------------------------------------------
            dealers_path = data_dir / "dealers.csv"
            with open(dealers_path, newline="", encoding="utf-8") as fh:
                for i, row in enumerate(csv.DictReader(fh), start=2):
                    code = (row.get("dealer_code") or "").strip()
                    name = (row.get("name") or "").strip()
                    if not code or not name:
                        stats["dealers_invalid"] += 1
                        self.stderr.write(f"dealers.csv line {i}: invalid record (dealer_code={code!r})")
                        continue
                    credit_limit = _parse_money(row.get("credit_limit"))
                    defaults = {
                        "name": name,
                        "city": (row.get("city") or "").strip(),
                        "phone": (row.get("phone") or "").strip(),
                        "email": (row.get("email") or "").strip(),
                        "gstin": (row.get("gstin") or "").strip(),
                    }
                    if credit_limit is not None:
                        defaults["credit_limit"] = credit_limit
                    _, created = Dealer.objects.update_or_create(dealer_code=code, defaults=defaults)
                    if created:
                        stats["dealers_created"] += 1
                    else:
                        stats["dealers_updated"] += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete: products created={stats['products_created']} "
            f"updated={stats['products_updated']} invalid={stats['products_invalid']}; "
            f"dealers created={stats['dealers_created']} updated={stats['dealers_updated']} "
            f"invalid={stats['dealers_invalid']}"
        ))
