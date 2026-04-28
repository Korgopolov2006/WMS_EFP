from django import forms
from django.core.exceptions import ValidationError

from .models import Order, OrderLine


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["number", "customer_name", "customer_phone", "customer_email", "source", "external_id"]
        widgets = {
            "number": forms.TextInput(attrs={"class": "form__input", "placeholder": "Например, ORD-001"}),
            "customer_name": forms.TextInput(attrs={"class": "form__input", "placeholder": "Имя клиента"}),
            "customer_phone": forms.TextInput(attrs={"class": "form__input", "placeholder": "+7 (999) 123-45-67"}),
            "customer_email": forms.EmailInput(attrs={"class": "form__input", "placeholder": "email@example.com"}),
            "source": forms.Select(attrs={"class": "form__input"}),
            "external_id": forms.TextInput(attrs={"class": "form__input", "placeholder": "ID из внешней системы"}),
        }


class OrderLineForm(forms.ModelForm):
    product_search = forms.CharField(
        label="Поиск товара (OEM/SKU/название)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form__input", "placeholder": "Начните вводить OEM, SKU или название"}),
    )

    class Meta:
        model = OrderLine
        fields = ["product", "qty_ordered", "price"]
        widgets = {
            "product": forms.HiddenInput(),
            "qty_ordered": forms.NumberInput(
                attrs={"class": "form__input", "min": 1, "step": 1, "placeholder": "Количество"}
            ),
            "price": forms.NumberInput(
                attrs={"class": "form__input", "min": 0, "step": "0.01", "placeholder": "Цена (опционально)"}
            ),
        }

    def clean_qty_ordered(self):
        value = self.cleaned_data.get("qty_ordered")
        if value is None:
            raise ValidationError("Количество обязательно.")
        if value != value.to_integral_value():
            raise ValidationError("Количество должно быть целым числом (шт).")
        if value <= 0:
            raise ValidationError("Количество должно быть больше нуля.")
        return value
