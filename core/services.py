"""Business services shared by the REST API, the assistant tools and management commands.

Money is handled with Decimal + ROUND_HALF_UP to keep every amount exact to the paisa.
Order status transitions, stock deduction and order numbering live here so the REST API
and the GenAI assistant use identical business rules.
"""
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import DailyOrderSeq, IdempotencyKey, Order, OrderItem, Product, Dealer

TAX_RATE = Decimal("0.18")
CENT = Decimal("0.01")


class ValidationError(Exception):
    """400 VALIDATION_ERROR."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFoundError(Exception):
    """404 NOT_FOUND."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class DuplicateError(Exception):
    """409 DUPLICATE."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class InsufficientStockError(Exception):
    """409 INSUFFICIENT_STOCK."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class InvalidTransitionError(Exception):
    """409 INVALID_TRANSITION."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class OrderLockedError(Exception):
    """409 ORDER_LOCKED."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class IdempotencyConflictError(Exception):
    """409 IDEMPOTENCY_CONFLICT."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or []


def money(value) -> str:
    """Render a Decimal amount as a string with exactly 2 decimals."""
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def next_order_number() -> str:
    """Generate a unique ORD-YYYYMMDD-NNNN number safe under concurrent calls."""
    today_kolkata = timezone.localdate()
    prefix = f"ORD-{today_kolkata.strftime('%Y%m%d')}-"
    with transaction.atomic():
        seq_row, _ = DailyOrderSeq.objects.get_or_create(day=today_kolkata)
        updated = DailyOrderSeq.objects.filter(day=today_kolkata).update(sequence=F("sequence") + 1)
        if not updated:  # defensive: row vanished between get_or_create and update
            DailyOrderSeq.objects.get_or_create(day=today_kolkata)
            DailyOrderSeq.objects.filter(day=today_kolkata).update(sequence=F("sequence") + 1)
        n = DailyOrderSeq.objects.get(day=today_kolkata).sequence
    candidate = f"{prefix}{n:04d}"
    while Order.objects.filter(order_number=candidate).exists():
        # Counter lost a race or numbers were created by another process: bump again.
        with transaction.atomic():
            DailyOrderSeq.objects.filter(day=today_kolkata).update(sequence=F("sequence") + 1)
            n = DailyOrderSeq.objects.get(day=today_kolkata).sequence
        candidate = f"{prefix}{n:04d}"
    return candidate


def validate_product_payload(data, *, partial=False, instance=None):
    """Validate product create/patch payloads; returns cleaned field dict."""
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    errors = []
    out = {}
    if not partial:
        sku = str(data.get("sku") or "").strip()
        if not sku:
            errors.append("sku is required")
        out["sku"] = sku
        name = str(data.get("name") or "").strip()
        if not name:
            errors.append("name is required")
        out["name"] = name
        out["category"] = str(data.get("category") or "").strip()
        out["brand"] = str(data.get("brand") or "").strip()
        out["vehicle_fitment"] = str(data.get("vehicle_fitment") or "")
        out["description"] = str(data.get("description") or "")
        if "price" not in data or data.get("price") is None:
            errors.append("price is required")
    else:
        for field in ("name", "category", "brand", "vehicle_fitment", "description"):
            if field in data:
                value = data.get(field)
                if value is not None and not isinstance(value, str):
                    errors.append(f"{field} must be a string")
                else:
                    out[field] = (value or "")
    if "price" in data and data.get("price") is not None:
        raw = data.get("price")
        try:
            price = Decimal(str(raw))
        except Exception:
            errors.append("price must be a positive number with at most 2 decimal places")
        else:
            if price <= 0:
                errors.append("price must be > 0")
            elif price != price.quantize(CENT, rounding=ROUND_HALF_UP):
                # more than 2 decimals (e.g. 10.999)
                errors.append("price must have at most 2 decimal places")
            else:
                out["price"] = price.quantize(CENT, rounding=ROUND_HALF_UP)
    if errors:
        raise ValidationError("; ".join(errors))
    return out


def create_product(data):
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    sku = str(data.get("sku") or "").strip()
    if not sku:
        raise ValidationError("sku is required")
    if Product.objects.filter(sku=sku).exists():
        raise DuplicateError(f"Product with sku '{sku}' already exists")
    fields = validate_product_payload(data, partial=False)
    return Product.objects.create(**fields, stock=0)


def update_product(sku, data):
    product = Product.objects.filter(sku=sku).first()
    if product is None:
        raise NotFoundError(f"Product '{sku}' not found")
    fields = validate_product_payload(data, partial=True, instance=product)
    if "sku" in fields and fields["sku"] != sku:
        raise ValidationError("sku cannot be changed")
    for k, v in fields.items():
        setattr(product, k, v)
    product.save()
    return product


def set_inventory(sku, payload):
    product = Product.objects.filter(sku=sku).first()
    if product is None:
        raise NotFoundError(f"Product '{sku}' not found")
    raw = payload.get("quantity")
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValidationError("quantity must be an integer >= 0")
    if raw < 0:
        raise ValidationError("quantity must be an integer >= 0")
    product.stock = raw
    product.save(update_fields=["stock", "updated_at"])
    return product


def list_dealers():
    return Dealer.objects.all().order_by("id")


def create_dealer(data):
    code = str(data.get("dealer_code") or "").strip()
    name = str(data.get("name") or "").strip()
    errors = []
    if not code:
        errors.append("dealer_code is required")
    if not name:
        errors.append("name is required")
    if errors:
        raise ValidationError(", ".join(errors))
    if Dealer.objects.filter(dealer_code=code).exists():
        raise DuplicateError(f"Dealer with dealer_code '{code}' already exists")
    kwargs = {"dealer_code": code, "name": name}
    if "city" in data:
        kwargs["city"] = str(data.get("city") or "")
    if "phone" in data:
        kwargs["phone"] = str(data.get("phone") or "")
    if "email" in data:
        kwargs["email"] = str(data.get("email") or "")
    if "gstin" in data:
        kwargs["gstin"] = str(data.get("gstin") or "")
    if "credit_limit" in data and data.get("credit_limit") not in (None, ""):
        try:
            kwargs["credit_limit"] = Decimal(str(data.get("credit_limit")))
        except Exception:
            raise ValidationError("credit_limit must be a number")
    return Dealer.objects.create(**kwargs)


def validate_order_items(items, *, require_int_qty=True):
    """Validate the raw items payload; returns [(sku, quantity)] with duplicates rejected."""
    if not isinstance(items, list) or len(items) == 0:
        raise ValidationError("items must be a non-empty list")
    seen = set()
    out = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"item {idx} must be an object")
        sku = str(item.get("sku") or "").strip()
        if not sku:
            raise ValidationError(f"item {idx} is missing sku")
        qty = item.get("quantity")
        if isinstance(qty, bool) or (require_int_qty and not isinstance(qty, int)) or (not require_int_qty and qty is None):
            raise ValidationError(f"item {idx}: quantity must be an integer >= 1")
        if require_int_qty and qty < 1:
            raise ValidationError(f"item {idx}: quantity must be an integer >= 1")
        if sku in seen:
            raise ValidationError(f"duplicate sku '{sku}' in items")
        seen.add(sku)
        out.append((sku, qty))
    return out


def compute_lines(skus_with_qty):
    """Build validated order lines using live catalogue prices. Raises ValidationError for unknown SKUs."""
    skus = [sku for sku, _ in skus_with_qty]
    products = {p.sku: p for p in Product.objects.filter(sku__in=skus)}
    missing = [sku for sku in skus if sku not in products]
    if missing:
        raise ValidationError(f"unknown sku(s): {', '.join(missing)}")
    lines = []
    for sku, qty in skus_with_qty:
        product = products[sku]
        unit_price = product.price
        line_subtotal = (unit_price * qty).quantize(CENT, rounding=ROUND_HALF_UP)
        line_tax = (line_subtotal * TAX_RATE).quantize(CENT, rounding=ROUND_HALF_UP)
        line_total = line_subtotal + line_tax
        lines.append({
            "item": None,
            "sku": sku,
            "name": product.name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_subtotal": line_subtotal,
            "line_tax": line_tax,
            "line_total": line_total,
        })
    return lines


def compute_totals(lines):
    subtotal = sum((l["line_subtotal"] for l in lines), Decimal("0.00"))
    tax_total = sum((l["line_tax"] for l in lines), Decimal("0.00"))
    grand_total = subtotal + tax_total
    return subtotal, tax_total, grand_total


def _persist_items(order, lines):
    product_ids = {p.sku: p for p in Product.objects.filter(sku__in=[l["sku"] for l in lines])}
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product=product_ids[l["sku"]],
            sku=l["sku"],
            name=l["name"],
            quantity=l["quantity"],
            unit_price=l["unit_price"],
            line_subtotal=l["line_subtotal"],
            line_tax=l["line_tax"],
            line_total=l["line_total"],
        )
        for l in lines
    ])


@transaction.atomic
def create_draft_order(dealer_id, raw_items, *, idempotency_key=None, request_body=None):
    """Create a DRAFT order. Uses the same validation anywhere an order is created."""
    if idempotency_key:
        body_hash = hashlib.sha256(json.dumps(request_body or {}, sort_keys=True).encode()).hexdigest()
        existing = IdempotencyKey.objects.filter(key=idempotency_key).first()
        if existing:
            if existing.request_hash != body_hash:
                raise IdempotencyConflictError("Idempotency-Key reused with a different request body")
            return existing.order, False
    dealer = Dealer.objects.filter(pk=dealer_id).first()
    if dealer is None:
        raise ValidationError(f"dealer_id {dealer_id} does not exist")
    validated = validate_order_items(raw_items)
    lines = compute_lines(validated)
    subtotal, tax_total, grand_total = compute_totals(lines)
    order = Order(
        order_number=next_order_number(),
        dealer=dealer,
        status=Order.STATUS_DRAFT,
        subtotal=subtotal,
        tax_total=tax_total,
        grand_total=grand_total,
    )
    order.save()
    _persist_items(order, lines)
    if idempotency_key:
        IdempotencyKey.objects.create(
            key=idempotency_key,
            request_hash=body_hash,
            order=order,
        )
    return order, True


@transaction.atomic
def replace_order_items(order_number, raw_items):
    """PUT on a DRAFT order replaces all items and recomputes totals."""
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    if order.status != Order.STATUS_DRAFT:
        raise OrderLockedError("Only DRAFT orders can be edited")
    validated = validate_order_items(raw_items)
    lines = compute_lines(validated)
    subtotal, tax_total, grand_total = compute_totals(lines)
    order.items.all().delete()
    _persist_items(order, lines)
    order.subtotal = subtotal
    order.tax_total = tax_total
    order.grand_total = grand_total
    order.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])
    return order


def _check_insufficient_stock(lines):
    """Return list of {'sku', 'available', 'requested'} for every short line."""
    skus = [l["sku"] for l in lines]
    products = {p.sku: p for p in Product.objects.filter(sku__in=skus)}
    details = []
    for l in lines:
        product = products[l["sku"]]
        if l["quantity"] > product.stock:
            details.append({"sku": l["sku"], "requested": l["quantity"], "available": product.stock})
    return details


@transaction.atomic
def confirm_order(order_number):
    """DRAFT -> CONFIRMED, locking unit prices and deducting stock atomically."""
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    if order.status != Order.STATUS_DRAFT:
        raise InvalidTransitionError(f"Cannot confirm an order in status {order.status}")
    lines = list(order.items.select_related("product").order_by("id"))
    items = [(l.sku, l.quantity) for l in lines]
    product_map = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=[s for s, _ in items])}
    with transaction.atomic():
        short = []
        for sku, qty in items:
            product = product_map[sku]
            if product.stock < qty:
                short.append({"sku": sku, "requested": qty, "available": product.stock})
        if short:
            names = []
            for d in short:
                product = product_map[d["sku"]]
                names.append(
                    f"Insufficient stock for {product.name or product_map[d['sku']].sku}. "
                    f"Available: {d['available']}, Requested: {d['requested']}"
                )
            raise InsufficientStockError(" ".join(names), details=[
                {"sku": d["sku"], "requested": d["requested"], "available": d["available"]} for d in short
            ])
        for sku, qty in items:
            Product.objects.filter(sku=sku).update(stock=F("stock") - qty)
        # lock prices: keep the current line values as-is; future price changes never affect them
    order.status = Order.STATUS_CONFIRMED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def dispatch_order(order_number):
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    if order.status != Order.STATUS_CONFIRMED:
        raise InvalidTransitionError(f"Cannot dispatch an order in status {order.status}")
    order.status = Order.STATUS_DISPATCHED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def deliver_order(order_number):
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    if order.status != Order.STATUS_DISPATCHED:
        raise InvalidTransitionError(f"Cannot deliver an order in status {order.status}")
    order.status = Order.STATUS_DELIVERED
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def cancel_order(order_number):
    """DRAFT -> CANCELLED (no stock effect) or CONFIRMED -> CANCELLED (restores stock exactly once)."""
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    if order.status == Order.STATUS_DRAFT:
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return order
    if order.status == Order.STATUS_CONFIRMED:
        for item in order.items.select_related("product"):
            Product.objects.filter(sku=item.sku).update(stock=F("stock") + item.quantity)
        order.status = Order.STATUS_CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return order
    raise InvalidTransitionError(f"Cannot cancel an order in status {order.status}")


def get_order(order_number):
    order = Order.objects.filter(order_number=order_number).first()
    if order is None:
        raise NotFoundError(f"Order '{order_number}' not found")
    return order


def order_to_dict(order) -> dict:
    items = []
    for item in order.items.select_related("product").order_by("id"):
        items.append({
            "sku": item.sku,
            "name": item.name,
            "quantity": item.quantity,
            "unit_price": money(item.unit_price),
            "line_subtotal": money(item.line_subtotal),
            "line_tax": money(item.line_tax),
            "line_total": money(item.line_total),
        })
    return {
        "order_number": order.order_number,
        "dealer_id": order.dealer_id,
        "status": order.status,
        "items": items,
        "subtotal": money(order.subtotal),
        "tax_total": money(order.tax_total),
        "grand_total": money(order.grand_total),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }
