from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Order, OrderLine, OrderPriority


class OrderForm(forms.ModelForm):
    SOURCE_CHOICES = (
        ("MANUAL", "Вручную в WMS"),
        ("PHONE", "Звонок клиента"),
        ("ONLINE", "Сайт / интернет-магазин"),
        ("POS", "Касса / магазин"),
        ("MARKETPLACE", "Маркетплейс"),
        ("API", "API / интеграция"),
    )

    customer_phone = forms.CharField(
        label="Телефон клиента",
        required=True,
        help_text="Нужен для связи при выдаче или уточнении заказа.",
        widget=forms.TextInput(attrs={"class": "form__input", "placeholder": "+7 (999) 123-45-67"}),
    )
    source = forms.ChoiceField(
        label="Откуда пришёл заказ",
        choices=SOURCE_CHOICES,
        required=True,
        help_text="Выберите понятный источник: вручную, звонок, сайт, касса, маркетплейс или интеграция.",
        widget=forms.Select(attrs={"class": "form__input"}),
    )
    external_id = forms.CharField(
        label="Номер во внешней системе",
        required=False,
        help_text="Заполняйте только если заказ пришёл с сайта, маркетплейса, кассы или API. Для ручного заказа можно оставить пустым.",
        widget=forms.TextInput(attrs={"class": "form__input", "placeholder": "Например: SITE-1042, OZON-7788"}),
    )
    priority = forms.ChoiceField(
        label="Важность заказа",
        choices=OrderPriority.choices,
        initial=OrderPriority.NORMAL,
        help_text="Влияет на очередность подбора и отгрузки: срочные задачи попадают выше в очереди.",
        widget=forms.Select(attrs={"class": "form__input"}),
    )
    shipping_due_at = forms.DateTimeField(
        label="Срок отгрузки",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="Если указан, сборщик и отгрузка увидят дедлайн. Просроченные задачи подсвечиваются.",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form__input"}),
    )

    class Meta:
        model = Order
        fields = [
            "number",
            "customer_name",
            "customer_phone",
            "customer_email",
            "priority",
            "shipping_due_at",
            "source",
            "external_id",
            "note",
        ]
        widgets = {
            "number": forms.TextInput(attrs={"class": "form__input", "placeholder": "Автоматически"}),
            "customer_name": forms.TextInput(attrs={"class": "form__input", "placeholder": "Имя клиента"}),
            "customer_email": forms.EmailInput(attrs={"class": "form__input", "placeholder": "email@example.com"}),
            "note": forms.Textarea(
                attrs={
                    "class": "form__input",
                    "rows": 3,
                    "placeholder": "Например: клиент просил позвонить за 30 минут; хрупкий товар; отгрузить только полный комплект.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["number"].required = False
        self.fields["number"].help_text = "Заполнится автоматически при создании заказа."
        self.fields["number"].widget.attrs["readonly"] = "readonly"
        self.fields["number"].widget.attrs["data-auto-field"] = "1"
        if not self.is_bound and not self.initial.get("number"):
            self.initial["number"] = Order.generate_next_number()
        if self.instance and self.instance.shipping_due_at and not self.is_bound:
            self.initial["shipping_due_at"] = timezone.localtime(self.instance.shipping_due_at).strftime("%Y-%m-%dT%H:%M")

    def clean_customer_phone(self):
        phone = (self.cleaned_data.get("customer_phone") or "").strip()
        digits = [ch for ch in phone if ch.isdigit()]
        if not phone:
            raise ValidationError("Укажите телефон клиента.")
        if len(digits) < 10:
            raise ValidationError("Телефон должен содержать минимум 10 цифр.")
        return phone

    def clean_external_id(self):
        return (self.cleaned_data.get("external_id") or "").strip()

    def clean_note(self):
        return (self.cleaned_data.get("note") or "").strip()

    def save(self, commit=True):
        order = super().save(commit=False)
        if not order.number:
            order.number = Order.generate_next_number()
        if commit:
            order.save()
            self.save_m2m()
        return order


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
