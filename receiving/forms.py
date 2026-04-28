from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import Product, StorageLocation, Warehouse

from .models import Receiving, ReceivingLine, Supplier
from .services import get_user_warehouses, suggest_storage_location


class ReceivingForm(forms.ModelForm):
    supplier = forms.ModelChoiceField(
        label="Поставщик",
        queryset=Supplier.objects.none(),
        empty_label="Выберите поставщика",
    )
    warehouse = forms.ModelChoiceField(
        label="Склад приёмки",
        queryset=Warehouse.objects.none(),
        empty_label="Выберите склад",
    )
    expected_at = forms.DateField(
        label="Плановая дата поставки",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date", "class": "form__input"},
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["number"].required = False
        self.fields["number"].widget.attrs.setdefault("placeholder", "Автоматически")
        self.fields["number"].widget.attrs.setdefault("class", "form__input")
        self.fields["number"].widget.attrs["readonly"] = "readonly"
        self.fields["number"].widget.attrs["data-auto-field"] = "1"
        self.fields["supplier"].widget.attrs.setdefault("class", "form__input")
        self.fields["supplier_doc_no"].required = False
        self.fields["supplier_doc_no"].widget.attrs.setdefault("class", "form__input")
        self.fields["supplier_doc_no"].widget.attrs.setdefault("placeholder", "Автоматически")
        self.fields["supplier_doc_no"].widget.attrs["readonly"] = "readonly"
        self.fields["supplier_doc_no"].widget.attrs["data-auto-field"] = "1"
        self.fields["warehouse"].widget.attrs.setdefault("class", "form__input")

        suppliers_qs = Supplier.objects.filter(is_active=True).order_by("name")
        self.fields["supplier"].queryset = suppliers_qs
        warehouse_qs = Warehouse.objects.filter(is_active=True).select_related("branch")
        if self.user is not None:
            warehouse_qs = get_user_warehouses(self.user)
        self.fields["warehouse"].queryset = warehouse_qs.order_by("branch__code", "code")

        is_new = not self.instance or not self.instance.pk
        if is_new:
            if not self.initial.get("number"):
                self.initial["number"] = Receiving.generate_next_number()
            if not self.initial.get("expected_at"):
                self.initial["expected_at"] = timezone.localdate()
            if not self.initial.get("supplier") and suppliers_qs.exists():
                self.initial["supplier"] = suppliers_qs.first()
            if not self.initial.get("warehouse") and warehouse_qs.exists():
                self.initial["warehouse"] = warehouse_qs.first()
        elif self.instance.supplier_name and not self.is_bound:
            supplier_obj = Supplier.objects.filter(name=self.instance.supplier_name).first()
            if supplier_obj:
                self.initial["supplier"] = supplier_obj
            if self.instance.warehouse_id:
                self.initial["warehouse"] = self.instance.warehouse_id
            if self.instance.expected_at:
                self.initial["expected_at"] = timezone.localtime(self.instance.expected_at).date()

        if not self.is_bound and self.initial.get("supplier") and not self.initial.get("supplier_doc_no"):
            initial_supplier = self.initial["supplier"]
            if isinstance(initial_supplier, Supplier):
                self.initial["supplier_doc_no"] = Receiving.generate_next_supplier_doc_number(
                    supplier_code=initial_supplier.code,
                    for_date=self.initial.get("expected_at") or timezone.localdate(),
                )

        self.order_fields(["number", "supplier", "warehouse", "supplier_doc_no", "expected_at"])

    class Meta:
        model = Receiving
        fields = ["number", "supplier_doc_no"]

    def save(self, commit=True):
        obj: Receiving = super().save(commit=False)
        supplier: Supplier = self.cleaned_data["supplier"]
        warehouse: Warehouse = self.cleaned_data["warehouse"]
        expected_date = self.cleaned_data.get("expected_at")

        obj.supplier_name = supplier.name
        obj.warehouse = warehouse

        if expected_date:
            dt_naive = datetime.combine(expected_date, time(hour=9, minute=0))
            if settings.USE_TZ:
                obj.expected_at = timezone.make_aware(dt_naive, timezone.get_current_timezone())
            else:
                obj.expected_at = dt_naive
        else:
            obj.expected_at = None

        if not obj.supplier_doc_no:
            obj.supplier_doc_no = Receiving.generate_next_supplier_doc_number(
                supplier_code=supplier.code,
                for_date=expected_date or timezone.localdate(),
            )

        if commit:
            obj.save()
            self.save_m2m()
        return obj

    def clean_warehouse(self):
        warehouse = self.cleaned_data.get("warehouse")
        if not warehouse:
            raise ValidationError("Выберите склад приёмки.")
        if self.user is None:
            return warehouse
        allowed_warehouses = get_user_warehouses(self.user)
        if not allowed_warehouses.filter(pk=warehouse.pk).exists():
            raise ValidationError("У вас нет доступа к выбранному складу.")
        return warehouse


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.setdefault("class", "form__input")
        self.fields["code"].widget.attrs.setdefault("placeholder", "Например: AUTOTRADE")
        self.fields["name"].widget.attrs.setdefault("class", "form__input")
        self.fields["name"].widget.attrs.setdefault("placeholder", "Название поставщика")

    def clean_code(self):
        raw = self.cleaned_data.get("code", "")
        normalized = "".join(ch for ch in raw.upper() if ch.isascii() and ch.isalnum())[:24]
        if not normalized:
            raise ValidationError("Код должен содержать латинские буквы и/или цифры.")
        return normalized


class ReceivingLineForm(forms.ModelForm):
    class Meta:
        model = ReceivingLine
        fields = ["product", "supplier_sku", "qty_expected", "qty_received", "storage_location"]

    def __init__(self, *args, user=None, warehouse=None, **kwargs):
        self.user = user
        self.warehouse = warehouse
        super().__init__(*args, **kwargs)
        self.fields["supplier_sku"].required = True
        self.fields["qty_expected"].widget.attrs.update({"class": "form__input", "min": 1, "step": 1})
        self.fields["qty_received"].widget.attrs.update({"class": "form__input", "min": 0, "step": 1})
        self.fields["storage_location"].required = False
        self.fields["storage_location"].widget.attrs.update({"class": "form__input"})

        locations_qs = StorageLocation.objects.select_related("zone", "zone__warehouse", "zone__warehouse__branch")
        if self.warehouse is not None:
            locations_qs = locations_qs.filter(zone__warehouse=self.warehouse)
        if self.user is not None:
            user_warehouses = get_user_warehouses(self.user)
            locations_qs = locations_qs.filter(zone__warehouse__in=user_warehouses)
        self.fields["storage_location"].queryset = locations_qs.order_by(
            "zone__warehouse__branch__code",
            "zone__warehouse__code",
            "zone__code",
            "code",
        )

        if not self.is_bound and self.user is not None and not self.initial.get("storage_location"):
            product_initial = self.initial.get("product")
            product_obj = None
            if isinstance(product_initial, Product):
                product_obj = product_initial
            elif isinstance(product_initial, int) or (isinstance(product_initial, str) and product_initial.isdigit()):
                product_obj = Product.objects.filter(pk=int(product_initial)).first()

            if product_obj:
                suggested = suggest_storage_location(product_obj, user=self.user, warehouse=self.warehouse)
                if suggested:
                    self.initial["storage_location"] = suggested.pk

    @staticmethod
    def _validate_piece_qty(value: Decimal | None, label: str, allow_zero: bool = False) -> Decimal:
        if value is None:
            raise ValidationError(f"{label} обязательно.")
        if value != value.to_integral_value():
            raise ValidationError(f"{label} должно быть целым числом (шт).")
        if allow_zero:
            if value < 0:
                raise ValidationError(f"{label} не может быть отрицательным.")
        elif value <= 0:
            raise ValidationError(f"{label} должно быть больше нуля.")
        return value

    def clean_qty_expected(self):
        value = self.cleaned_data.get("qty_expected")
        return self._validate_piece_qty(value, "Ожидаемое количество", allow_zero=False)

    def clean_qty_received(self):
        value = self.cleaned_data.get("qty_received")
        return self._validate_piece_qty(value, "Принятое количество", allow_zero=True)

    def clean_storage_location(self):
        location = self.cleaned_data.get("storage_location")
        if not location or self.user is None:
            if location and self.warehouse and location.zone.warehouse_id != self.warehouse.id:
                raise ValidationError("Место хранения должно относиться к складу документа приёмки.")
            return location

        allowed_warehouses = get_user_warehouses(self.user)
        if not allowed_warehouses.filter(pk=location.zone.warehouse_id).exists():
            raise ValidationError("Это место хранения недоступно для вашего филиала/склада.")
        if self.warehouse and location.zone.warehouse_id != self.warehouse.id:
            raise ValidationError("Место хранения должно относиться к складу документа приёмки.")
        return location
