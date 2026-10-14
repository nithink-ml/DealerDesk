"""PUT /api/inventory/{sku}/ sets the available quantity to exactly this value."""
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import NotFoundError, ValidationError, set_inventory
from .views import error_response, parsed_body


class InventoryUpdateView(APIView):
    def put(self, request, sku):
        try:
            product = set_inventory(sku, parsed_body(request))
        except NotFoundError as e:
            return error_response("NOT_FOUND", e.message, e.details)
        except ValidationError as e:
            return error_response("VALIDATION_ERROR", e.message, e.details)
        return Response({"sku": product.sku, "quantity": product.stock})
