from django.urls import path, re_path

from . import assistant_views, inventory_views, ml_views, orders_views, supplier_sync, views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("health", views.health, name="health_noslash"),
    # products & inventory
    path("products/", views.ProductViewSet.as_view({"get": "list", "post": "create"})),
    path("products/<str:sku>/", views.ProductViewSet.as_view({"get": "retrieve", "patch": "partial_update"})),
    path("inventory/<str:sku>/", inventory_views.InventoryUpdateView.as_view()),
    # dealers
    path("dealers/", views.DealerViewSet.as_view({"get": "list", "post": "create"})),
    path("dealers/<int:pk>/", views.DealerViewSet.as_view({"get": "retrieve"})),
    # orders
    path("orders/", orders_views.OrderListCreateView.as_view()),
    path("orders/<str:order_number>/", orders_views.OrderDetailView.as_view()),
    path("orders/<str:order_number>/confirm/", orders_views.OrderConfirmView.as_view()),
    path("orders/<str:order_number>/dispatch/", orders_views.OrderDispatchView.as_view()),
    path("orders/<str:order_number>/deliver/", orders_views.OrderDeliverView.as_view()),
    path("orders/<str:order_number>/cancel/", orders_views.OrderCancelView.as_view()),
    # supplier sync
    path("sync/supplier/", supplier_sync.SupplierSyncView.as_view()),
    # forecasting / reorder
    path("forecast/<str:sku>/", ml_views.ForecastDetailView.as_view()),
    path("reorder-suggestions/", ml_views.ReorderSuggestionsView.as_view()),
    # GenAI dealer assistant
    path("assistant/chat/", assistant_views.AssistantChatView.as_view()),
    # catch-all for unknown API endpoints
    re_path(r"^.*$", views.api_not_found),
]
