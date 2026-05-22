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
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@example.com')
password = os.environ['DJANGO_SUPERUSER_PASSWORD']
defaults = {'email': email, 'is_staff': True, 'is_superuser': True}
try:
    defaults['role'] = 'ADMIN'
except Exception:
    pass
user, created = User.objects.get_or_create(username=username, defaults=defaults)
if created:
    user.set_password(password)
    user.save(update_fields=['password'])
    print('Created superuser:', username)
else:
    changed_fields = []
    if not user.is_staff:
        user.is_staff = True
        changed_fields.append('is_staff')
    if not user.is_superuser:
        user.is_superuser = True
        changed_fields.append('is_superuser')
    if hasattr(user, 'role') and getattr(user, 'role') != 'ADMIN':
        user.role = 'ADMIN'
        changed_fields.append('role')
    if changed_fields:
        user.save(update_fields=changed_fields)
    print('Superuser already exists:', username)
"
fi

exec "$@"
