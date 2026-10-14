"""Real database-backed tools for the GenAI dealer assistant.

Each tool is a plain Python function executed server-side and validated before
the LLM ever sees the result. search_parts and check_stock are read-only;
create_draft_order reuses core.services.create_draft_order so the assistant
cannot create an order that bypasses the backend's business rules. No tool
can confirm an order — the state machine only ever writes status DRAFT.
"""
from __future__ import annotations

from ..models import Product, Dealer
from ..services import ValidationError, create_draft_order, order_to_dict


def _strip_plural(term: str) -> str:
    """Cheap singulariser so 'pads' matches 'Pad Set' and 'filters' matches 'filter'."""
    t = term.lower()
    if len(t) > 3 and t.endswith("ies"):  # batteries → batteri (matches 'Battery Set' via prefix?)
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def search_parts(query: str = "", vehicle: str = "", category: str = "", brand: str = "", sku: str = "", limit: int = 8):
    """Search the catalogue by SKU, name keywords, vehicle fitment, category or brand."""
    from django.db.models import Q
    qs = Product.objects.all()
    if sku:
        qs = qs.filter(sku__iexact=sku.strip())
    if query:
        q = query.strip()
        terms = [t for t in q.split() if t][:5]
        for term in terms:
            stem = _strip_plural(term)
            qs = qs.filter(
                Q(name__icontains=term) | Q(description__icontains=term) | Q(sku__icontains=term)
                | Q(name__icontains=stem) | Q(description__icontains=stem)
            )
    if vehicle:
        qs = qs.filter(vehicle_fitment__icontains=vehicle.strip())
    if category:
        qs = qs.filter(category__iexact=category.strip())
    if brand:
        qs = qs.filter(brand__icontains=brand.strip())
    results = [
        {
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "brand": p.brand,
            "vehicle_fitment": p.vehicle_fitment,
            "price": f"{p.price:.2f}",
            "stock": p.stock,
        }
        for p in qs.order_by("sku")[: max(1, min(limit, 20))]
    ]
    return {"results": results, "count": results.__len__()}


def check_stock(sku: str):
    """Live inventory lookup. Distinguishes unknown SKU from zero stock."""
    product = Product.objects.filter(sku__iexact=(sku or "").strip()).first()
    if product is None:
        return {"sku": sku, "exists": False, "stock": None,
                "message": f"Unknown SKU '{sku}' — no such product in the catalogue."}
    return {"sku": product.sku, "exists": True, "stock": product.stock,
            "name": product.name,
            "message": f"{product.name} — {product.stock} units available."}


def create_draft_order_tool(dealer_id, items):
    """Create a DRAFT order through the shared backend service. Never confirms."""
    if not isinstance(items, list):
        return {"error": "items must be a list of {sku, quantity}"}
    validated = []
    for item in items:
        if not isinstance(item, dict):
            return {"error": "each item must be an object with sku and quantity"}
        sku = str(item.get("sku") or "").strip()
        qty = item.get("quantity")
        if not sku:
            return {"error": "each item must include a sku"}
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            return {"error": f"quantity for {sku} must be an integer >= 1"}
        validated.append({"sku": sku, "quantity": qty})
    if not validated:
        return {"error": "items must not be empty"}
    try:
        order, created = create_draft_order(dealer_id, validated)
    except ValidationError as e:
        return {"error": e.message}
    except Exception as e:  # surface a clean failure, never a fabricated success
        return {"error": f"draft order creation failed: {e}"}
    data = order_to_dict(order)
    return {"order_number": data["order_number"], "status": data["status"],
            "grand_total": data["grand_total"], "subtotal": data["subtotal"],
            "tax_total": data["tax_total"], "items": data["items"],
            "dealer_id": data["dealer_id"]}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_parts",
            "description": "Search the parts catalogue by keywords, vehicle fitment, category, brand or exact SKU. Returns matching products with current price and stock.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Free-text keywords, e.g. 'brake pads'"},
                    "vehicle": {"type": "string", "description": "Vehicle make/model, e.g. 'Bajaj Pulsar 150'"},
                    "category": {"type": "string", "description": "Exact category name, e.g. 'Brakes'"},
                    "brand": {"type": "string", "description": "Brand name"},
                    "sku": {"type": "string", "description": "Exact SKU lookup"},
                    "limit": {"type": "integer", "description": "Max results (1-20)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_stock",
            "description": "Get the current available stock for one SKU.",
            "parameters": {
                "type": "object",
                "properties": {"sku": {"type": "string", "description": "Exact SKU"}},
                "required": ["sku"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft_order",
            "description": "Create a DRAFT order for the dealer with a list of {sku, quantity} items. Orders stay in DRAFT status and are never confirmed by the assistant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string"},
                                "quantity": {"type": "integer", "minimum": 1},
                            },
                            "required": ["sku", "quantity"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
]
