# Docker-запуск WMS EFP

Этот вариант нужен для быстрой передачи проекта коллеге: база PostgreSQL, Redis и Django поднимаются через `docker compose`.

## 1. Первый запуск

1. Скопируйте файл окружения:

   ```bash
   copy .env.docker.example .env.docker
   ```

   На Linux/macOS:

   ```bash
   cp .env.docker.example .env.docker
   ```

2. Соберите и запустите проект:

   ```bash
   docker compose up --build
   ```

3. Откройте сайт:

   ```text
   http://127.0.0.1:8000/
   ```

4. Войдите под тестовым администратором:

   ```text
   login: admin
   password: admin12345
   ```

При старте контейнер сам выполняет:

- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`
- создание администратора из `.env.docker`, если его ещё нет.

Если в папке `backups/` есть файл `wms_demo_dump.sql`, PostgreSQL автоматически восстановит его при первом создании базы. Это значит, что коллега сразу увидит ваши справочники, товары, склады, остатки, 3D-разметку и заказы без ручного импорта.

## 2. Остановка и повторный запуск

Остановить:

```bash
docker compose down
```

Запустить снова:

```bash
docker compose up
```

Данные при обычном `docker compose down` сохраняются.

## 3. Где хранятся данные

Главные данные проекта — справочники, товары, склады, остатки, заказы, задачи, пользователи — лежат в PostgreSQL.

В Docker они сохраняются в volume:

```text
postgres_data
```

Загруженные файлы и изображения сохраняются в volume:

```text
media_data
```

Резервные копии сохраняются в папку проекта:

```text
backups/
```

Важно: данные не должны храниться внутри контейнера `web`, потому что контейнер можно пересоздать. Сохранять нужно volume базы и media.

## 4. Как полностью удалить данные

Осторожно: команда удалит базу и загруженные файлы.

```bash
docker compose down -v
```

После этого следующий запуск создаст пустую базу заново.

## 5. Как передать коллеге текущие справочники

Если нужно отправить не пустой проект, а проект с вашими товарами, складами и остатками, создайте дамп PostgreSQL с фиксированным именем:

```bash
docker compose exec db pg_dump -U wms -d wms_autoparts > backups/wms_demo_dump.sql
```

Передайте коллеге:

- код проекта;
- файл `backups/wms_demo_dump.sql`.

При первом запуске контейнеров дамп восстановится автоматически:

```bash
docker compose up --build
```

Важно: официальный контейнер PostgreSQL выполняет автоимпорт только при первом создании volume `postgres_data`. Если коллега уже запускал проект и база успела создаться пустой, нужно один раз удалить volume и запустить снова:

```bash
docker compose down -v
docker compose up --build
```

## 6. Как включить Celery worker

Обычная проверка сайта может идти без отдельного worker. Если нужно проверить фоновые задачи:

```bash
docker compose --profile worker up --build
```

## 7. Полезные команды

Открыть Django shell:

```bash
docker compose exec web python manage.py shell
```

Создать суперпользователя вручную:

```bash
docker compose exec web python manage.py createsuperuser
```

Выполнить тесты:

```bash
docker compose exec web python manage.py test
```

Посмотреть логи:

```bash
docker compose logs -f web
```

## 8. Что важно для проверки диплома

Для коллеги лучше передавать проект вместе с заполненной базой, потому что справочники — это не код, а данные:

- бренды;
- категории;
- товары;
- склады;
- зоны хранения;
- места хранения;
- остатки;
- пользователи и роли;
- 3D-разметка склада;
- заказы и задачи.

Именно поэтому основной способ сохранения — PostgreSQL volume или SQL-дамп.
