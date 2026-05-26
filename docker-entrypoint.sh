#!/usr/bin/env sh
set -eu

if [ "${POSTGRES_HOST:-}" ]; then
  echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
  until nc -z "${POSTGRES_HOST}" "${POSTGRES_PORT:-5432}"; do
    sleep 1
  done
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  python manage.py shell -c "
import os
from django.contrib.auth import get_user_model
from accounts.constants import Roles

User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.environ['DJANGO_SUPERUSER_PASSWORD']

user, created = User.objects.get_or_create(
    username=username,
    defaults={
        'email': email,
        'role': Roles.ADMIN,
        'is_staff': True,
        'is_superuser': True,
        'is_active': True,
    },
)

changed_fields = []
if created or not user.has_usable_password():
    user.set_password(password)
    changed_fields.append('password')
if user.email != email:
    user.email = email
    changed_fields.append('email')
if not user.is_staff:
    user.is_staff = True
    changed_fields.append('is_staff')
if not user.is_superuser:
    user.is_superuser = True
    changed_fields.append('is_superuser')
if not user.is_active:
    user.is_active = True
    changed_fields.append('is_active')
if getattr(user, 'role', None) != Roles.ADMIN:
    user.role = Roles.ADMIN
    changed_fields.append('role')
if changed_fields:
    user.save(update_fields=sorted(set(changed_fields)))

print(('Created' if created else 'Prepared') + ' superuser:', username)
"
fi

exec "$@"
