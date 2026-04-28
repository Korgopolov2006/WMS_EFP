from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db import transaction

from accounts.constants import Roles

from api.models import ApiToken


class Command(BaseCommand):
    help = "Создаёт/обновляет пользователя роли INTEGRATION и выпускает API Bearer-токен."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--name", default="Integration token")
        parser.add_argument("--rotate", action="store_true", help="Перевыпустить токен (создать новый и деактивировать старые).")

    @transaction.atomic
    def handle(self, *args, **options):
        username: str = options["username"]
        token_name: str = options["name"]
        rotate: bool = bool(options["rotate"])

        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"role": Roles.INTEGRATION, "is_active": True})
        if not created:
            if getattr(user, "role", None) != Roles.INTEGRATION:
                user.role = Roles.INTEGRATION
                user.save(update_fields=["role"])

        if rotate:
            ApiToken.objects.filter(user=user, is_active=True).update(is_active=False)

        token_value = ApiToken.generate_token()
        api_token = ApiToken.objects.create(user=user, name=token_name, token=token_value, is_active=True)

        self.stdout.write(self.style.SUCCESS(f"username: {user.username} (role={user.role})"))
        self.stdout.write(self.style.SUCCESS(f"token_id: {api_token.id}"))
        self.stdout.write(self.style.SUCCESS(f"token: {token_value}"))

