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
user, created = User.objects.get_or_create(username=username, defaults={'email': email, 'role': Roles.ADMIN, 'is_staff': True, 'is_superuser': True})
if created:
    user.set_password(password)
    user.save(update_fields=['password'])
    print('Created superuser:', username)
else:
    changed = False
    if not user.is_staff:
        user.is_staff = True
        changed = True
    if not user.is_superuser:
        user.is_superuser = True
        changed = True
    if getattr(user, 'role', None) != Roles.ADMIN:
        user.role = Roles.ADMIN
        changed = True
    if changed:
        user.save()
    print('Superuser already exists:', username)
"
fi

exec "$@"
