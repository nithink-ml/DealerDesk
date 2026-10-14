"""API views: products, inventory, dealers (orders/sync/ML/assistant live in their own modules)."""
import json

from django.db import connection
from django.db.models import Q
from django.http import JsonResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Dealer, Product
from .pagination import DefaultPagination
from .serializers import DealerSerializer, ProductSerializer
from .services import (
    DuplicateError,
    NotFoundError,
    ValidationError,
    create_dealer,
    create_product,
    update_product,
)

ERROR_STATUS = {
    "VALIDATION_ERROR": 400,
    "NOT_FOUND": 404,
    "DUPLICATE": 409,
    "ORDER_LOCKED": 409,
    "IDEMPOTENCY_CONFLICT": 409,
}


def error_response(code, message, details=None):
    return Response({"error": {"code": code, "message": message, "details": details or []}},
                    status=ERROR_STATUS.get(code, status.HTTP_400_BAD_REQUEST))


def parsed_body(request):
    """Robust JSON body: DRF usually parses request.data; fall back to raw JSON."""
    data = getattr(request, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    try:
        raw = request.body
        parsed = json.loads(raw or b"{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


@api_view(["GET"])
def health(request):
    """GET /api/health/ — checks application and PostgreSQL database readiness.

    Returns 200 {"status": "ok"} when healthy.
    Returns 503 {"status": "unavailable", "error": "Database unavailable"} if connection fails.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return Response(
            {"status": "unavailable", "error": "Database unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


def api_not_found(request, *args, **kwargs):
    """Fallback 404 handler for unknown API endpoints returning exact contract envelope.

    Defined as a plain Django view returning JsonResponse so DRF browsable API does not
    treat it as an APIView parent breadcrumb during reverse resolution.
    """
    return JsonResponse(
        {"error": {"code": "NOT_FOUND", "message": f"Endpoint '{request.path}' not found", "details": []}},
        status=404,
    )


class ProductViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin,
                     mixins.RetrieveModelMixin, mixins.UpdateModelMixin):
    queryset = Product.objects.all().order_by("sku")
    serializer_class = ProductSerializer
    lookup_field = "sku"
    pagination_class = DefaultPagination
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = Product.objects.all().order_by("sku")
        params = self.request.query_params
        search = params.get("search")
        if search:
            s = search.strip()
            qs = qs.filter(Q(sku__icontains=s) | Q(name__icontains=s) | Q(brand__icontains=s))
        category = params.get("category")
        if category:
            qs = qs.filter(category__iexact=category)
        vehicle = params.get("vehicle")
        if vehicle:
            qs = qs.filter(vehicle_fitment__icontains=vehicle)
        return qs

    def retrieve(self, request, *args, **kwargs):
        sku = self.kwargs.get("sku")
        product = Product.objects.filter(sku=sku).first()
        if product is None:
            return error_response("NOT_FOUND", f"Product '{sku}' not found")
        return Response(ProductSerializer(product).data)

    def create(self, request, *args, **kwargs):
        try:
            product = create_product(parsed_body(request))
        except ValidationError as e:
            return error_response("VALIDATION_ERROR", e.message, e.details)
        except DuplicateError as e:
            return error_response("DUPLICATE", e.message, e.details)
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        sku = self.kwargs.get("sku")
        try:
            product = update_product(sku, parsed_body(request))
        except NotFoundError as e:
            return error_response("NOT_FOUND", e.message, e.details)
        except ValidationError as e:
            return error_response("VALIDATION_ERROR", e.message, e.details)
        return Response(ProductSerializer(product).data)


class DealerViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.CreateModelMixin,
                    mixins.RetrieveModelMixin):
    queryset = Dealer.objects.all().order_by("id")
    serializer_class = DealerSerializer
    pagination_class = DefaultPagination

    def create(self, request, *args, **kwargs):
        try:
            dealer = create_dealer(parsed_body(request))
        except ValidationError as e:
            return error_response("VALIDATION_ERROR", e.message, e.details)
        except DuplicateError as e:
            return error_response("DUPLICATE", e.message, e.details)
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        dealer = Dealer.objects.filter(pk=kwargs.get("pk")).first()
        if dealer is None:
            return error_response("NOT_FOUND", f"Dealer {kwargs.get('pk')} not found")
        return Response(DealerSerializer(dealer).data)
