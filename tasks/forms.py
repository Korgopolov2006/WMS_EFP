from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model

from accounts.constants import Roles
from .models import Task, TaskPriority, TaskType
from .services import TaskService


class ManualTaskForm(forms.ModelForm):
    assigned_to = forms.ModelChoiceField(
        label="Исполнитель",
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label="Оставить в общей очереди",
    )

    class Meta:
        model = Task
        fields = ["task_type", "title", "description", "priority", "assigned_to"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form__input")

        self.fields["title"].widget.attrs.setdefault("placeholder", "Например: Проверить остатки на SHELF-01")
        self.fields["description"].widget.attrs.setdefault("placeholder", "Что именно нужно сделать и где")
        self.fields["priority"].initial = TaskPriority.NORMAL

        self.fields["task_type"].choices = self._task_type_choices()

        user_model = get_user_model()
        if self._is_admin_user:
            self.fields["assigned_to"].queryset = user_model.objects.filter(is_active=True).exclude(
                role=Roles.INTEGRATION
            ).order_by("username")
        else:
            self.fields["assigned_to"].required = False
            self.fields["assigned_to"].widget = forms.HiddenInput()
            self.initial["assigned_to"] = self.user

    @property
    def _is_admin_user(self) -> bool:
        return bool(self.user and (self.user.is_superuser or self.user.role == Roles.ADMIN))

    def _task_type_choices(self):
        if self._is_admin_user:
            return TaskType.choices

        allowed_types = set(TaskService._get_task_types_for_role(getattr(self.user, "role", "")))
        allowed_types.add(TaskType.OTHER)
        return [(code, label) for code, label in TaskType.choices if code in allowed_types]

    def clean_assigned_to(self):
        assigned_to = self.cleaned_data.get("assigned_to")
        if not self._is_admin_user:
            return self.user
        return assigned_to

    def clean(self):
        cleaned = super().clean()
        assigned_to = cleaned.get("assigned_to")
        task_type = cleaned.get("task_type")
        if assigned_to and task_type:
            probe = Task(task_type=task_type)
            if not probe.can_be_assigned_to(assigned_to):
                self.add_error("assigned_to", "Эта задача не подходит роли выбранного исполнителя.")
        return cleaned
