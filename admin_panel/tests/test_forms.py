"""
Тесты форм административной панели.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from admin_panel.forms import BackupCreateForm, UserCreateForm, UserEditForm

User = get_user_model()


# ─────────────────────────────────────────────────────────────
#  UserCreateForm
# ─────────────────────────────────────────────────────────────

class TestUserCreateForm(TestCase):

    def _valid_data(self, **overrides):
        data = {
            "username": "newuser",
            "email": "newuser@test.ru",
            "first_name": "Иван",
            "last_name": "Тест",
            "role": "STOREKEEPER",
        }
        data.update(overrides)
        return data

    def test_valid_form(self):
        form = UserCreateForm(data=self._valid_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_username(self):
        form = UserCreateForm(data=self._valid_data(username=""))
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_missing_email(self):
        form = UserCreateForm(data=self._valid_data(email=""))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_invalid_email_format(self):
        form = UserCreateForm(data=self._valid_data(email="not-an-email"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_duplicate_username(self):
        User.objects.create_user(username="existinguser", email="ex@test.ru",
                                  password="Pass1!ABCDEFGH")
        form = UserCreateForm(data=self._valid_data(username="existinguser"))
        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_duplicate_email(self):
        User.objects.create_user(username="other", email="taken@test.ru",
                                  password="Pass1!ABCDEFGH")
        form = UserCreateForm(data=self._valid_data(email="taken@test.ru"))
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_invalid_role(self):
        form = UserCreateForm(data=self._valid_data(role="INVALID_ROLE"))
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    def test_optional_fields(self):
        """first_name и last_name — не обязательны."""
        data = {"username": "minimaluser", "email": "min@test.ru", "role": "LOADER"}
        form = UserCreateForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_email_lowercased(self):
        form = UserCreateForm(data=self._valid_data(email="Upper@TEST.RU"))
        form.is_valid()
        self.assertEqual(form.cleaned_data["email"], "upper@test.ru")


# ─────────────────────────────────────────────────────────────
#  UserEditForm
# ─────────────────────────────────────────────────────────────

class TestUserEditForm(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="editme",
            email="editme@test.ru",
            password="Pass1!ABCDEFGH",
            role="STOREKEEPER",
        )

    def _valid_data(self, **overrides):
        data = {
            "first_name": "Иван",
            "last_name": "Тест",
            "email": "editme@test.ru",
            "role": "LOADER",
            "is_active": True,
        }
        data.update(overrides)
        return data

    def test_valid_edit(self):
        form = UserEditForm(data=self._valid_data(), instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_change_role(self):
        form = UserEditForm(data=self._valid_data(role="ANALYST"), instance=self.user)
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.role, "ANALYST")

    def test_deactivate_user(self):
        form = UserEditForm(data=self._valid_data(is_active=False), instance=self.user)
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertFalse(user.is_active)

    def test_duplicate_email_prevented(self):
        other = User.objects.create_user(
            username="other_edit", email="other_edit@test.ru", password="Pass1!ABCDEFGH"
        )
        form = UserEditForm(
            data=self._valid_data(email="other_edit@test.ru"),
            instance=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_same_email_allowed(self):
        """Пользователь может сохранить тот же email."""
        form = UserEditForm(
            data=self._valid_data(email="editme@test.ru"),
            instance=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)


# ─────────────────────────────────────────────────────────────
#  BackupCreateForm
# ─────────────────────────────────────────────────────────────

class TestBackupCreateForm(TestCase):

    def test_empty_notes_valid(self):
        form = BackupCreateForm(data={"notes": ""})
        self.assertTrue(form.is_valid())

    def test_with_notes_valid(self):
        form = BackupCreateForm(data={"notes": "Перед обновлением системы"})
        self.assertTrue(form.is_valid())

    def test_notes_too_long(self):
        form = BackupCreateForm(data={"notes": "x" * 501})
        self.assertFalse(form.is_valid())
        self.assertIn("notes", form.errors)
