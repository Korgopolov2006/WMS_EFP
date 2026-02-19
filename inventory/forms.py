from django import forms

from catalog.models import StorageZone
from inventory.models import Inventory


class InventoryForm(forms.ModelForm):
    class Meta:
        model = Inventory
        fields = ["number", "zone"]
        widgets = {
            "number": forms.TextInput(attrs={"class": "form__input"}),
            "zone": forms.Select(attrs={"class": "form__input"}),
        }
