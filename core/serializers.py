from rest_framework import serializers

from .models import Dealer, Product


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["sku", "name", "category", "brand", "vehicle_fitment", "price", "stock", "description"]
        read_only_fields = ["stock", "sku"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["price"] = f"{instance.price:.2f}"
        data["stock"] = int(instance.stock)
        return data


class DealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = ["id", "dealer_code", "name", "city", "phone", "email", "gstin", "credit_limit"]

    def validate(self, attrs):
        if "dealer_code" in attrs and not str(attrs["dealer_code"]).strip():
            raise serializers.ValidationError({"dealer_code": "dealer_code is required"})
        if "name" in attrs and not str(attrs["name"]).strip():
            raise serializers.ValidationError({"name": "name is required"})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["credit_limit"] = f"{instance.credit_limit:.2f}" if instance.credit_limit is not None else None
        return data
