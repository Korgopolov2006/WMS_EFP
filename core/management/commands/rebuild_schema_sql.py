from __future__ import annotations

from pathlib import Path

from django.core.management import BaseCommand


class Command(BaseCommand):
    help = "Полностью пересоздаёт db/schema.sql на основе миграций (sqlmigrate) без подключения к БД."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="db/schema.sql",
            help="Путь к выходному файлу (по умолчанию db/schema.sql)",
        )
        parser.add_argument(
            "--apps",
            default="accounts,catalog",
            help="Список приложений через запятую, для которых собирается DDL (по умолчанию accounts,catalog)",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])

        # В дипломе требование — единый PostgreSQL DDL-файл.
        # Генерацию делаем оффлайн (без подключения к БД), но в PostgreSQL-диалекте.
        # На старте проекта это намеренно “source of truth” и пересоздаётся целиком.
        ddl = """-- WMS автозапчастей — PostgreSQL schema (DDL)
-- Этот файл генерируется командой:
--   python manage.py rebuild_schema_sql
-- При изменении структуры БД пересоздавайте файл полностью.

BEGIN;

-- =========================
-- Django system tables (минимальный набор)
-- =========================

CREATE TABLE IF NOT EXISTS django_migrations (
    id BIGSERIAL PRIMARY KEY,
    app VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    applied TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS django_content_type (
    id BIGSERIAL PRIMARY KEY,
    app_label VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    CONSTRAINT django_content_type_app_label_model_uniq UNIQUE (app_label, model)
);

CREATE TABLE IF NOT EXISTS auth_permission (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    content_type_id BIGINT NOT NULL REFERENCES django_content_type (id) ON DELETE CASCADE,
    codename VARCHAR(100) NOT NULL,
    CONSTRAINT auth_permission_content_type_codename_uniq UNIQUE (content_type_id, codename)
);

CREATE INDEX IF NOT EXISTS auth_permission_content_type_idx ON auth_permission (content_type_id);

CREATE TABLE IF NOT EXISTS auth_group (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS auth_group_permissions (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES auth_group (id) ON DELETE CASCADE,
    permission_id BIGINT NOT NULL REFERENCES auth_permission (id) ON DELETE CASCADE,
    CONSTRAINT auth_group_permissions_group_permission_uniq UNIQUE (group_id, permission_id)
);

CREATE INDEX IF NOT EXISTS auth_group_permissions_group_idx ON auth_group_permissions (group_id);
CREATE INDEX IF NOT EXISTS auth_group_permissions_permission_idx ON auth_group_permissions (permission_id);

-- =========================
-- accounts_user (AUTH_USER_MODEL)
-- =========================

CREATE TABLE IF NOT EXISTS accounts_user (
    id BIGSERIAL PRIMARY KEY,

    password VARCHAR(128) NOT NULL,
    last_login TIMESTAMPTZ NULL,

    is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
    username VARCHAR(150) NOT NULL UNIQUE,
    first_name VARCHAR(150) NOT NULL DEFAULT '',
    last_name VARCHAR(150) NOT NULL DEFAULT '',
    email VARCHAR(254) NOT NULL DEFAULT '',

    is_staff BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    date_joined TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    role VARCHAR(32) NOT NULL DEFAULT 'STOREKEEPER'
);

CREATE INDEX IF NOT EXISTS accounts_user_role_idx ON accounts_user (role);

ALTER TABLE accounts_user
    ADD CONSTRAINT IF NOT EXISTS accounts_user_role_check
    CHECK (role IN (
        'ADMIN',
        'STOREKEEPER',
        'SMALL_PARTS_PICKER',
        'LOADER',
        'SALES_MANAGER',
        'ANALYST',
        'INTEGRATION'
    ));

-- M2M таблицы пользователя (Groups / Permissions)
CREATE TABLE IF NOT EXISTS accounts_user_groups (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES auth_group (id) ON DELETE CASCADE,
    CONSTRAINT accounts_user_groups_user_group_uniq UNIQUE (user_id, group_id)
);

CREATE INDEX IF NOT EXISTS accounts_user_groups_user_idx ON accounts_user_groups (user_id);
CREATE INDEX IF NOT EXISTS accounts_user_groups_group_idx ON accounts_user_groups (group_id);

CREATE TABLE IF NOT EXISTS accounts_user_user_permissions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE CASCADE,
    permission_id BIGINT NOT NULL REFERENCES auth_permission (id) ON DELETE CASCADE,
    CONSTRAINT accounts_user_user_permissions_user_perm_uniq UNIQUE (user_id, permission_id)
);

CREATE INDEX IF NOT EXISTS accounts_user_user_permissions_user_idx ON accounts_user_user_permissions (user_id);
CREATE INDEX IF NOT EXISTS accounts_user_user_permissions_perm_idx ON accounts_user_user_permissions (permission_id);

-- =========================
-- catalog справочники
-- =========================

CREATE TABLE IF NOT EXISTS catalog_brand (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog_category (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR(120) NOT NULL UNIQUE,
    parent_id BIGINT NULL REFERENCES catalog_category (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS catalog_category_parent_idx ON catalog_category (parent_id);

CREATE TABLE IF NOT EXISTS catalog_vehiclemake (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog_vehiclemodel (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    make_id BIGINT NOT NULL REFERENCES catalog_vehiclemake (id) ON DELETE RESTRICT,
    name VARCHAR(120) NOT NULL,
    CONSTRAINT uniq_vehicle_model_make_name UNIQUE (make_id, name)
);

CREATE INDEX IF NOT EXISTS catalog_vehiclemodel_make_idx ON catalog_vehiclemodel (make_id);

CREATE TABLE IF NOT EXISTS catalog_storagezonetype (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS catalog_storagezone (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    zone_type_id BIGINT NOT NULL REFERENCES catalog_storagezonetype (id) ON DELETE RESTRICT,
    description TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS catalog_storagezone_zone_type_idx ON catalog_storagezone (zone_type_id);

CREATE TABLE IF NOT EXISTS catalog_storagelocation (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    zone_id BIGINT NOT NULL REFERENCES catalog_storagezone (id) ON DELETE RESTRICT,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(120) NOT NULL DEFAULT '',
    aisle VARCHAR(16) NOT NULL DEFAULT '',
    rack VARCHAR(16) NOT NULL DEFAULT '',
    shelf VARCHAR(16) NOT NULL DEFAULT '',
    level VARCHAR(16) NOT NULL DEFAULT '',
    max_weight_kg NUMERIC(10,3) NULL,
    CONSTRAINT uniq_location_zone_code UNIQUE (zone_id, code)
);

CREATE INDEX IF NOT EXISTS catalog_storagelocation_zone_idx ON catalog_storagelocation (zone_id);

CREATE TABLE IF NOT EXISTS catalog_product (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    internal_sku VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,

    oem_number VARCHAR(64) NOT NULL,
    analog_number VARCHAR(64) NOT NULL DEFAULT '',

    brand_id BIGINT NOT NULL REFERENCES catalog_brand (id) ON DELETE RESTRICT,
    category_id BIGINT NOT NULL REFERENCES catalog_category (id) ON DELETE RESTRICT,

    weight_kg NUMERIC(10,3) NULL,
    length_cm NUMERIC(10,2) NULL,
    width_cm NUMERIC(10,2) NULL,
    height_cm NUMERIC(10,2) NULL,

    packaging_type VARCHAR(16) NOT NULL DEFAULT 'SMALL',
    photo VARCHAR(100) NULL
);

CREATE INDEX IF NOT EXISTS idx_product_oem ON catalog_product (oem_number);
CREATE INDEX IF NOT EXISTS idx_product_analog ON catalog_product (analog_number);
CREATE INDEX IF NOT EXISTS idx_product_brand_cat ON catalog_product (brand_id, category_id);

ALTER TABLE catalog_product
    ADD CONSTRAINT IF NOT EXISTS catalog_product_packaging_type_check
    CHECK (packaging_type IN ('SMALL','LARGE','PALLET'));

ALTER TABLE catalog_product
    ADD CONSTRAINT IF NOT EXISTS catalog_product_weight_nonneg CHECK (weight_kg IS NULL OR weight_kg >= 0);
ALTER TABLE catalog_product
    ADD CONSTRAINT IF NOT EXISTS catalog_product_length_nonneg CHECK (length_cm IS NULL OR length_cm >= 0);
ALTER TABLE catalog_product
    ADD CONSTRAINT IF NOT EXISTS catalog_product_width_nonneg CHECK (width_cm IS NULL OR width_cm >= 0);
ALTER TABLE catalog_product
    ADD CONSTRAINT IF NOT EXISTS catalog_product_height_nonneg CHECK (height_cm IS NULL OR height_cm >= 0);

CREATE TABLE IF NOT EXISTS catalog_productapplicability (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    vehicle_model_id BIGINT NOT NULL REFERENCES catalog_vehiclemodel (id) ON DELETE RESTRICT,

    CONSTRAINT uniq_product_vehicle_model UNIQUE (product_id, vehicle_model_id)
);

CREATE INDEX IF NOT EXISTS catalog_productapplicability_product_idx ON catalog_productapplicability (product_id);
CREATE INDEX IF NOT EXISTS catalog_productapplicability_vehicle_idx ON catalog_productapplicability (vehicle_model_id);

CREATE TABLE IF NOT EXISTS catalog_productcrossreference (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    from_product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    to_product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    relation_type VARCHAR(16) NOT NULL,
    note VARCHAR(255) NOT NULL DEFAULT '',

    CONSTRAINT chk_xref_not_self CHECK (from_product_id <> to_product_id),
    CONSTRAINT uniq_xref_from_to_type UNIQUE (from_product_id, to_product_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_xref_from_type ON catalog_productcrossreference (from_product_id, relation_type);

ALTER TABLE catalog_productcrossreference
    ADD CONSTRAINT IF NOT EXISTS catalog_productcrossreference_relation_type_check
    CHECK (relation_type IN ('ANALOG','OEM','REPLACED_BY'));

-- =========================
-- api (integration tokens)
-- =========================

CREATE TABLE IF NOT EXISTS api_apitoken (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    token VARCHAR(64) NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS api_apitoken_token_idx ON api_apitoken (token);
CREATE INDEX IF NOT EXISTS api_apitoken_user_idx ON api_apitoken (user_id);
CREATE INDEX IF NOT EXISTS api_apitoken_is_active_idx ON api_apitoken (is_active);

-- =========================
-- receiving (приёмка)
-- =========================

CREATE TABLE IF NOT EXISTS receiving_receiving (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    number VARCHAR(32) NOT NULL UNIQUE,
    supplier_name VARCHAR(255) NOT NULL,
    supplier_doc_no VARCHAR(64) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    expected_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS receiving_receiving_status_idx ON receiving_receiving (status);

CREATE TABLE IF NOT EXISTS receiving_receivingline (
    id BIGSERIAL PRIMARY KEY,
    receiving_id BIGINT NOT NULL REFERENCES receiving_receiving (id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    supplier_sku VARCHAR(64) NOT NULL DEFAULT '',
    qty_expected NUMERIC(10,2) NOT NULL DEFAULT 0,
    qty_received NUMERIC(10,2) NOT NULL DEFAULT 0,
    storage_location_id BIGINT NULL REFERENCES catalog_storagelocation (id) ON DELETE RESTRICT,
    has_serial_numbers BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS receiving_line_receiving_idx ON receiving_receivingline (receiving_id);
CREATE INDEX IF NOT EXISTS receiving_line_product_idx ON receiving_receivingline (product_id);

CREATE TABLE IF NOT EXISTS receiving_receivingserial (
    id BIGSERIAL PRIMARY KEY,
    line_id BIGINT NOT NULL REFERENCES receiving_receivingline (id) ON DELETE CASCADE,
    serial_number VARCHAR(128) NOT NULL,
    CONSTRAINT uniq_receivingserial_line_serial UNIQUE (line_id, serial_number)
);

CREATE INDEX IF NOT EXISTS receiving_serial_line_idx ON receiving_receivingserial (line_id);

-- =========================
-- sessions
-- =========================

CREATE TABLE IF NOT EXISTS django_session (
    session_key VARCHAR(40) PRIMARY KEY,
    session_data TEXT NOT NULL,
    expire_date TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS django_session_expire_date_idx ON django_session (expire_date);

COMMIT;
"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ddl, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Готово: {output_path.as_posix()}"))

