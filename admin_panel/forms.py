"""
Формы административной панели WMS.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from accounts.constants import ROLE_CHOICES
from catalog.models import Branch

User = get_user_model()


class UserCreateForm(forms.Form):
    """Форма создания пользователя (пароль генерируется автоматически)."""

    username = forms.CharField(
        label="Логин",
        max_length=150,
        help_text="Только буквы, цифры и @/./+/-/_",
        widget=forms.TextInput(attrs={"autofocus": True}),
    )
    first_name = forms.CharField(
        label="Имя",
        max_length=150,
        required=False,
    )
    last_name = forms.CharField(
        label="Фамилия",
        max_length=150,
        required=False,
    )
    email = forms.EmailField(
        label="Email",
        help_text="На этот адрес будут отправлены учётные данные.",
    )
    role = forms.ChoiceField(
        label="Роль",
        choices=ROLE_CHOICES,
    )
    branches = forms.ModelMultipleChoiceField(
        label="Филиалы",
        queryset=Branch.objects.filter(is_active=True).order_by("code"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Оставьте пустым — пользователь получит доступ ко всем филиалам роли.",
    )

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Пользователь с таким логином уже существует.")
        return username

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Пользователь с таким email уже зарегистрирован.")
        return email


class UserEditForm(forms.ModelForm):
    """Форма редактирования пользователя (без поля пароля)."""

    branches = forms.ModelMultipleChoiceField(
        label="Филиалы",
        queryset=Branch.objects.filter(is_active=True).order_by("code"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role", "is_active", "branches"]
        labels = {
            "first_name": "Имя",
            "last_name": "Фамилия",
            "email": "Email",
            "role": "Роль",
            "is_active": "Активен",
        }
        widgets = {
            "role": forms.Select(choices=ROLE_CHOICES),
        }

    def clean_email(self) -> str:
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Пользователь с таким email уже зарегистрирован.")
        return email


class BackupCreateForm(forms.Form):
    """Форма создания резервной копии."""

    notes = forms.CharField(
        label="Комментарий",
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Необязательный комментарий к резервной копии…"}),
    )


class BackupUploadForm(forms.Form):
    """Форма загрузки готового файла резервной копии."""

    backup_file = forms.FileField(
        label="Файл резервной копии",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".sql,.sqlite3,.db",
                "class": "file-picker__input",
                "style": "position:absolute;width:1px;height:1px;opacity:0;overflow:hidden;clip-path:inset(50%);pointer-events:none;",
                "tabindex": "-1",
            }
        ),
    )
    notes = forms.CharField(
        label="Комментарий",
        max_length=500,
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "backup-upload-comment",
            }
        ),
    )

    def clean_backup_file(self):
        file = self.cleaned_data["backup_file"]
        name = (file.name or "").lower()
        if not name.endswith((".sql", ".sqlite3", ".db")):
            raise ValidationError("Загрузите файл резервной копии в формате .sql, .sqlite3 или .db.")
        if file.size <= 0:
            raise ValidationError("Файл резервной копии пустой.")
        max_size = 500 * 1024 * 1024
        if file.size > max_size:
            raise ValidationError("Файл слишком большой. Максимальный размер — 500 МБ.")
        return file


# ─────────────────────────────────────────────────────────────
#  WMS-сущности: Склады, Поставщики
# ─────────────────────────────────────────────────────────────

class WarehouseForm(forms.ModelForm):
    """Форма создания / редактирования склада."""

    from catalog.models import Branch

    class Meta:
        from catalog.models import Warehouse
        model = Warehouse
        fields = ["branch", "code", "name", "width_m", "length_m", "height_m", "is_active"]
        labels = {
            "branch": "Филиал",
            "code": "Код склада",
            "name": "Название",
            "width_m": "Ширина, м",
            "length_m": "Длина, м",
            "height_m": "Высота, м",
            "is_active": "Активен",
        }
        widgets = {
            "code": forms.TextInput(attrs={"autofocus": True}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from catalog.models import Branch
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("code")

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get("branch")
        code = cleaned.get("code")
        if branch and code:
            from catalog.models import Warehouse
            qs = Warehouse.objects.filter(branch=branch, code=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error("code", "Склад с таким кодом уже существует в данном филиале.")
        return cleaned


class SupplierForm(forms.ModelForm):
    """Форма создания / редактирования поставщика."""

    class Meta:
        from receiving.models import Supplier
        model = Supplier
        fields = ["code", "name", "is_active"]
        labels = {
            "code": "Код поставщика",
            "name": "Название",
            "is_active": "Активен",
        }
        widgets = {
            "code": forms.TextInput(attrs={"autofocus": True}),
        }

    def clean_code(self) -> str:
        code = self.cleaned_data["code"].strip().upper()
        from receiving.models import Supplier
        qs = Supplier.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Поставщик с таким кодом уже существует.")
        return code

    def clean_name(self) -> str:
        name = self.cleaned_data["name"].strip()
        from receiving.models import Supplier
        qs = Supplier.objects.filter(name=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Поставщик с таким названием уже существует.")
        return name
