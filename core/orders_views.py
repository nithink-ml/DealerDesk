"""Order API: create/list/retrieve draft orders plus the full lifecycle endpoints.

Every calculation and state change lives in core.services so the REST API and the
GenAI assistant share identical business rules.
"""
import re

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order
from .services import (
    IdempotencyConflictError,
    InsufficientStockError,
    InvalidTransitionError,
    NotFoundError,
    OrderLockedError,
    ValidationError,
    cancel_order,
    confirm_order,
    create_draft_order,
    deliver_order,
    dispatch_order,
    get_order,
    order_to_dict,
    replace_order_items,
)

ORDER_NUMBER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _error_response(exc, default_status=status.HTTP_400_BAD_REQUEST):
    code = {
        IdempotencyConflictError: "IDEMPOTENCY_CONFLICT",
        InsufficientStockError: "INSUFFICIENT_STOCK",
        InvalidTransitionError: "INVALID_TRANSITION",
        OrderLockedError: "ORDER_LOCKED",
        NotFoundError: "NOT_FOUND",
    }.get(type(exc), "VALIDATION_ERROR")
    return Response({"error": {"code": code, "message": exc.message, "details": exc.details}},
                    status=exc.status if hasattr(exc, "status") else default_status)


def _body(request):
    """Parsed JSON body as dict; '{}' when the request has no JSON object."""
    import json as _json
    data = getattr(request, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = _json.loads(data)
            return parsed if isinstance(parsed, dict) else {}
        except _json.JSONDecodeError:
            return {}
    try:
        # Django WSGIRequest fallback (non-DRF code paths)
        raw = request.body
        parsed = _json.loads(raw or b"{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


class OrderListCreateView(APIView):
    """POST /api/orders/ and GET /api/orders/."""

    def post(self, request):
        import hashlib
        import json
        from django.db import IntegrityError
        from .models import IdempotencyKey

        body = _body(request)
        idem_key = request.headers.get("Idempotency-Key")
        dealer_id = body.get("dealer_id")
        if isinstance(dealer_id, bool) or not isinstance(dealer_id, int):
            return Response({"error": {"code": "VALIDATION_ERROR",
                                       "message": "dealer_id must be an integer", "details": []}},
                            status=status.HTTP_400_BAD_REQUEST)
        items = body.get("items")
        try:
            order, created = create_draft_order(dealer_id, items, idempotency_key=idem_key,
                                                request_body=body)
        except IntegrityError:
            # Race condition: another thread inserted the same idempotency key concurrently
            if idem_key:
                existing = IdempotencyKey.objects.filter(key=idem_key).first()
                if existing:
                    body_hash = hashlib.sha256(json.dumps(body or {}, sort_keys=True).encode()).hexdigest()
                    if existing.request_hash != body_hash:
                        return Response({"error": {"code": "IDEMPOTENCY_CONFLICT",
                                                   "message": "Idempotency-Key reused with a different request body",
                                                   "details": []}},
                                        status=status.HTTP_409_CONFLICT)
                    return Response(order_to_dict(existing.order), status=status.HTTP_200_OK)
            return Response({"error": {"code": "VALIDATION_ERROR",
                                       "message": "Order creation failed due to conflict", "details": []}},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValidationError, IdempotencyConflictError) as e:
            return _error_response(
                e,
                status.HTTP_409_CONFLICT if isinstance(e, IdempotencyConflictError) else status.HTTP_400_BAD_REQUEST,
            )
        return Response(order_to_dict(order),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def get(self, request):
        from .pagination import DefaultPagination
        qs = Order.objects.all().order_by("-created_at", "-id")
        dealer_id = request.query_params.get("dealer_id")
        if dealer_id:
            qs = qs.filter(dealer_id=dealer_id)
        order_status = request.query_params.get("status")
        if order_status:
            qs = qs.filter(status=order_status.upper())
        paginator = DefaultPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response([order_to_dict(o) for o in page])


class OrderDetailView(APIView):
    """GET /api/orders/{order_number}/ and PUT /api/orders/{order_number}/."""

    def get(self, request, order_number):
        try:
            order = get_order(order_number)
        except NotFoundError as e:
            return _error_response(e, status.HTTP_404_NOT_FOUND)
        return Response(order_to_dict(order))

    def put(self, request, order_number):
        body = _body(request)
        try:
            order = replace_order_items(order_number, body.get("items"))
        except (NotFoundError, OrderLockedError, ValidationError) as e:
            return _error_response(e, status.HTTP_409_CONFLICT if isinstance(e, OrderLockedError)
                                   else status.HTTP_404_NOT_FOUND if isinstance(e, NotFoundError)
                                   else status.HTTP_400_BAD_REQUEST)
        return Response(order_to_dict(order))


def _action(request, order_number, fn):
    try:
        order = fn(order_number)
    except (NotFoundError, InsufficientStockError, InvalidTransitionError) as e:
        code = {NotFoundError: "NOT_FOUND",
                InsufficientStockError: "INSUFFICIENT_STOCK",
                InvalidTransitionError: "INVALID_TRANSITION"}[type(e)]
        return Response(
            {"error": {"code": code, "message": e.message, "details": e.details}},
            status=status.HTTP_404_NOT_FOUND if type(e) is NotFoundError else status.HTTP_409_CONFLICT,
        )
    return Response(order_to_dict(order))


class OrderConfirmView(APIView):
    def post(self, request, order_number):
        return _action(request, order_number, confirm_order)


class OrderDispatchView(APIView):
    def post(self, request, order_number):
        return _action(request, order_number, dispatch_order)


class OrderDeliverView(APIView):
    def post(self, request, order_number):
        return _action(request, order_number, deliver_order)


class OrderCancelView(APIView):
    def post(self, request, order_number):
        return _action(request, order_number, cancel_order)
