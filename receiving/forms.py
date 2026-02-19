from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import Receiving, ReceivingLine


class ReceivingForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["number"].required = False
        self.fields["number"].widget.attrs.setdefault("placeholder", "Автоматически")
        self.fields["number"].widget.attrs.setdefault("class", "form__input")
        self.fields["supplier_name"].widget.attrs.setdefault("class", "form__input")
        self.fields["supplier_doc_no"].widget.attrs.setdefault("class", "form__input")

        is_new = not self.instance or not self.instance.pk
        if is_new:
            if not self.initial.get("number"):
                self.initial["number"] = Receiving.generate_next_number()
            if not self.initial.get("expected_at"):
                self.initial["expected_at"] = timezone.localdate()

    class Meta:
        model = Receiving
        fields = ["number", "supplier_name", "supplier_doc_no", "expected_at"]
        widgets = {
            "expected_at": forms.DateInput(attrs={"type": "date", "class": "form__input"}),
        }


class ReceivingLineForm(forms.ModelForm):
    class Meta:
        model = ReceivingLine
        fields = ["product", "supplier_sku", "qty_expected", "qty_received", "storage_location", "has_serial_numbers"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supplier_sku"].required = True
