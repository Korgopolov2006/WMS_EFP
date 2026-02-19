from __future__ import annotations

from django import forms

from .models import (
    Brand,
    Category,
    Product,
    ProductCrossReference,
    StorageZone,
    StorageLocation,
    StorageZoneType,
    VehicleMake,
    VehicleModel,
)


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ["name"]


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent"]


class VehicleMakeForm(forms.ModelForm):
    class Meta:
        model = VehicleMake
        fields = ["name"]


class VehicleModelForm(forms.ModelForm):
    class Meta:
        model = VehicleModel
        fields = ["make", "name"]


class StorageZoneTypeForm(forms.ModelForm):
    class Meta:
        model = StorageZoneType
        fields = ["code", "name", "description", "sort_order"]


class StorageZoneForm(forms.ModelForm):
    class Meta:
        model = StorageZone
        fields = ["warehouse", "code", "name", "zone_type", "description"]


class StorageLocationForm(forms.ModelForm):
    class Meta:
        model = StorageLocation
        fields = [
            "zone",
            "code",
            "name",
            "aisle",
            "rack",
            "shelf",
            "level",
            "max_weight_kg",
        ]


class ProductForm(forms.ModelForm):
    applicability = forms.ModelMultipleChoiceField(
        label="Применимость (модели ТС)",
        queryset=VehicleModel.objects.select_related("make").all().order_by("make__name", "name"),
        required=False,
        widget=forms.SelectMultiple(attrs={"size": "8"}),
    )

    class Meta:
        model = Product
        fields = [
            "internal_sku",
            "name",
            "oem_number",
            "analog_number",
            "brand",
            "category",
            "weight_kg",
            "length_cm",
            "width_cm",
            "height_cm",
            "packaging_type",
            "photo",
            "applicability",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["applicability"].initial = self.instance.applicability.all()

    def save(self, commit: bool = True):
        obj = super().save(commit=commit)
        if commit:
            obj.applicability.set(self.cleaned_data.get("applicability") or [])
        return obj


class ProductCrossReferenceForm(forms.ModelForm):
    class Meta:
        model = ProductCrossReference
        fields = ["to_product", "relation_type", "note"]

