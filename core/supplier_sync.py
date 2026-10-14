"""Supplier sync: POST /api/sync/supplier/.

Fetches every page of the supplier feed (retries on 429/5xx/connection errors, max
5 attempts per request), rejects invalid items, de-duplicates by latest updated_at,
then applies created/updated/unchanged counts inside a single transaction. Our stock
is never changed by supplier data. Any unrecoverable failure changes nothing.
"""
import logging
import time
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Product

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
MAX_ATTEMPTS = 5
PAGE_LIMIT = 20  # server clamps larger values to this


def _valid_price(raw):
    if raw is None:
        return False
    try:
        price = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return False
    if price <= 0:
        return False
    # at most 2 decimals
    return price == price.quantize(CENT, rounding=ROUND_HALF_UP)


def _parse_updated_at(raw):
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_full_feed():
    """Follow next_cursor until None, retrying transient failures. Returns (items, pages, requests).

    Raises RuntimeError if any request cannot be completed within its attempt budget
    or the API key is rejected.
    """
    base = settings.SUPPLIER_API_URL.rstrip("/")
    api_key = settings.SUPPLIER_API_KEY
    items = []
    pages = 0
    requests_made = 0
    cursor = None
    backoff = 0.5
    while True:
        params = {"limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        attempt = 0
        while True:
            attempt += 1
            requests_made += 1
            try:
                resp = requests.get(
                    f"{base}/v1/products",
                    params=params,
                    headers={"X-Api-Key": api_key},
                    timeout=30,
                )
            except requests.RequestException:
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(f"connection failed after {attempt} attempts")
                time.sleep(min(backoff, 5))
                backoff = min(backoff * 2, 8)
                continue
            if resp.status_code == 200:
                break
            if resp.status_code == 429:
                retry_after = 1
                try:
                    retry_after = int(resp.headers.get("Retry-After", 1))
                except (TypeError, ValueError):
                    pass
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError("rate-limited beyond retry budget")
                time.sleep(max(retry_after, 0))
                continue  # 429 retries do not change backoff; Retry-After governs
            if 500 <= resp.status_code < 600:
                if attempt >= MAX_ATTEMPTS:
                    raise RuntimeError(f"supplier 5xx after {attempt} attempts")
                time.sleep(min(backoff, 5))
                backoff = min(backoff * 2, 8)
                continue
            raise RuntimeError(f"supplier returned status {resp.status_code}")
        pages += 1
        try:
            payload = resp.json()
        except ValueError:
            raise RuntimeError("supplier returned non-JSON body")
        page_items = payload.get("items") or []
        items.extend(page_items)
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return items, pages, requests_made


def apply_feed(items):
    """De-duplicate by latest updated_at, reject invalid items, apply inside one transaction.

    Returns (created, updated, unchanged, rejected).
    """
    rejected = []
    by_sku = {}
    for item in items:
        sku = str(item.get("sku") or "").strip()
        if not sku:
            rejected.append({"supplier_sku": item.get("supplier_sku"), "reason": "missing or empty sku"})
            continue
        if not _valid_price(item.get("price")):
            rejected.append({"supplier_sku": item.get("supplier_sku"), "reason": "invalid price"})
            continue
        updated_at = _parse_updated_at(item.get("updated_at"))
        existing = by_sku.get(sku)
        if existing is None or (updated_at or datetime.min.replace(tzinfo=dt_timezone.utc)) > (
                existing[1] or datetime.min.replace(tzinfo=dt_timezone.utc)):
            by_sku[sku] = (item, updated_at)
    TEXT_FIELDS = ("name", "category", "brand", "vehicle_fitment", "description")
    created, updated, unchanged = 0, 0, 0
    with transaction.atomic():
        for sku, (item, _) in by_sku.items():
            product = Product.objects.select_for_update().filter(sku=sku).first()
            price = Decimal(str(item["price"])).quantize(CENT, rounding=ROUND_HALF_UP)
            if product is None:
                Product.objects.create(
                    sku=sku,
                    name=str(item.get("name") or ""),
                    category=str(item.get("category") or ""),
                    brand=str(item.get("brand") or ""),
                    vehicle_fitment=str(item.get("vehicle_fitment") or ""),
                    description=str(item.get("description") or ""),
                    price=price,
                    stock=0,
                )
                created += 1
                continue
            changed = False
            for f in TEXT_FIELDS:
                new_value = str(item.get(f) or "")
                if getattr(product, f) != new_value:
                    setattr(product, f, new_value)
                    changed = True
            if product.price != price:
                product.price = price
                changed = True
            if changed:
                product.save()
                updated += 1
            else:
                unchanged += 1
    return created, updated, unchanged, rejected


class SupplierSyncView(APIView):
    def post(self, request):
        try:
            items, pages, requests_made = fetch_full_feed()
        except RuntimeError as e:
            logger.warning("supplier sync failed: %s", e)
            return Response({"error": {"code": "SUPPLIER_UNAVAILABLE",
                                       "message": str(e) or "supplier feed could not be fetched",
                                       "details": []}},
                            status=status.HTTP_502_BAD_GATEWAY)
        created, updated, unchanged, rejected = apply_feed(items)
        return Response({
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "rejected": rejected,
            "pages_fetched": pages,
            "requests_made": requests_made,
        })
