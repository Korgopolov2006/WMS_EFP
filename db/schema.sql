-- WMS автозапчастей — PostgreSQL schema (DDL)
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
-- catalog (Branch, Warehouse, WarehouseAccess)
-- =========================

CREATE TABLE IF NOT EXISTS catalog_branch (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS catalog_warehouse (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    branch_id BIGINT NOT NULL REFERENCES catalog_branch (id) ON DELETE RESTRICT,
    code VARCHAR(32) NOT NULL,
    name VARCHAR(255) NOT NULL,
    width_m NUMERIC(8,2) NOT NULL DEFAULT 30.0,
    length_m NUMERIC(8,2) NOT NULL DEFAULT 40.0,
    height_m NUMERIC(8,2) NOT NULL DEFAULT 8.0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uniq_warehouse_branch_code UNIQUE (branch_id, code)
);

CREATE INDEX IF NOT EXISTS catalog_warehouse_branch_idx ON catalog_warehouse (branch_id);

CREATE TABLE IF NOT EXISTS catalog_warehouseaccess (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE CASCADE,
    warehouse_id BIGINT NOT NULL REFERENCES catalog_warehouse (id) ON DELETE CASCADE,
    access_level VARCHAR(16) NOT NULL DEFAULT 'VIEW',
    CONSTRAINT uniq_warehouse_access_user_warehouse UNIQUE (user_id, warehouse_id)
);

CREATE INDEX IF NOT EXISTS catalog_warehouseaccess_user_idx ON catalog_warehouseaccess (user_id);
CREATE INDEX IF NOT EXISTS catalog_warehouseaccess_warehouse_idx ON catalog_warehouseaccess (warehouse_id);

ALTER TABLE catalog_warehouseaccess
    ADD CONSTRAINT IF NOT EXISTS catalog_warehouseaccess_access_level_check
    CHECK (access_level IN ('VIEW','EDIT','ADMIN'));

CREATE TABLE IF NOT EXISTS accounts_user_branches (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE CASCADE,
    branch_id BIGINT NOT NULL REFERENCES catalog_branch (id) ON DELETE CASCADE,
    CONSTRAINT accounts_user_branches_user_branch_uniq UNIQUE (user_id, branch_id)
);

CREATE INDEX IF NOT EXISTS accounts_user_branches_user_idx ON accounts_user_branches (user_id);
CREATE INDEX IF NOT EXISTS accounts_user_branches_branch_idx ON accounts_user_branches (branch_id);

-- Обновляем catalog_storagezone для связи с warehouse
ALTER TABLE catalog_storagezone
    ADD COLUMN IF NOT EXISTS warehouse_id BIGINT NULL REFERENCES catalog_warehouse (id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS catalog_storagezone_warehouse_idx ON catalog_storagezone (warehouse_id);

-- =========================
-- inventory (Stock, Inventory)
-- =========================

CREATE TABLE IF NOT EXISTS inventory_stock (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    storage_location_id BIGINT NOT NULL REFERENCES catalog_storagelocation (id) ON DELETE RESTRICT,
    qty_available NUMERIC(10,2) NOT NULL DEFAULT 0,
    qty_reserved NUMERIC(10,2) NOT NULL DEFAULT 0,
    batch_no VARCHAR(64) NOT NULL DEFAULT '',
    expiry_date DATE NULL,
    CONSTRAINT uniq_stock_product_location_batch UNIQUE (product_id, storage_location_id, batch_no)
);

CREATE INDEX IF NOT EXISTS idx_stock_product ON inventory_stock (product_id);
CREATE INDEX IF NOT EXISTS idx_stock_location ON inventory_stock (storage_location_id);
CREATE INDEX IF NOT EXISTS idx_stock_qty_available ON inventory_stock (qty_available);

CREATE TABLE IF NOT EXISTS inventory_inventory (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    number VARCHAR(32) NOT NULL UNIQUE,
    zone_id BIGINT NULL REFERENCES catalog_storagezone (id) ON DELETE RESTRICT,
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS inventory_inventory_status_idx ON inventory_inventory (status);

CREATE TABLE IF NOT EXISTS inventory_inventoryline (
    id BIGSERIAL PRIMARY KEY,
    inventory_id BIGINT NOT NULL REFERENCES inventory_inventory (id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    storage_location_id BIGINT NOT NULL REFERENCES catalog_storagelocation (id) ON DELETE RESTRICT,
    qty_book NUMERIC(10,2) NOT NULL DEFAULT 0,
    qty_actual NUMERIC(10,2) NULL,
    discrepancy NUMERIC(10,2) NOT NULL DEFAULT 0,
    CONSTRAINT uniq_inv_line_inv_prod_loc UNIQUE (inventory_id, product_id, storage_location_id)
);

CREATE INDEX IF NOT EXISTS inventory_inventoryline_inventory_idx ON inventory_inventoryline (inventory_id);

-- =========================
-- picking (Order, OrderLine, PickingTask, PickingLine)
-- =========================

CREATE TABLE IF NOT EXISTS picking_order (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    number VARCHAR(32) NOT NULL UNIQUE,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(32) NOT NULL DEFAULT '',
    customer_email VARCHAR(254) NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT',
    source VARCHAR(32) NOT NULL DEFAULT 'MANUAL',
    external_id VARCHAR(64) NOT NULL DEFAULT '',
    confirmed_at TIMESTAMPTZ NULL,
    picked_at TIMESTAMPTZ NULL,
    shipped_at TIMESTAMPTZ NULL,
    reserved_at_window BOOLEAN NOT NULL DEFAULT FALSE,
    window_number VARCHAR(16) NOT NULL DEFAULT '',
    created_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    picked_by_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_order_status ON picking_order (status);
CREATE INDEX IF NOT EXISTS idx_order_number ON picking_order (number);

ALTER TABLE picking_order
    ADD CONSTRAINT IF NOT EXISTS picking_order_status_check
    CHECK (status IN ('DRAFT','CONFIRMED','IN_PICKING','PICKED','RESERVED','SHIPPED','CANCELLED'));

CREATE TABLE IF NOT EXISTS picking_orderline (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES picking_order (id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    qty_ordered NUMERIC(10,2) NOT NULL,
    qty_picked NUMERIC(10,2) NOT NULL DEFAULT 0,
    price NUMERIC(10,2) NULL,
    CONSTRAINT uniq_order_line_order_product UNIQUE (order_id, product_id)
);

CREATE INDEX IF NOT EXISTS picking_orderline_order_idx ON picking_orderline (order_id);
CREATE INDEX IF NOT EXISTS picking_orderline_product_idx ON picking_orderline (product_id);

CREATE TABLE IF NOT EXISTS picking_pickingtask (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    order_id BIGINT NOT NULL REFERENCES picking_order (id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    zone_type_code VARCHAR(32) NOT NULL,
    assigned_to_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_picking_task_status ON picking_pickingtask (status);
CREATE INDEX IF NOT EXISTS idx_picking_task_zone ON picking_pickingtask (zone_type_code);

ALTER TABLE picking_pickingtask
    ADD CONSTRAINT IF NOT EXISTS picking_pickingtask_status_check
    CHECK (status IN ('PENDING','IN_PROGRESS','COMPLETED','CANCELLED'));

CREATE TABLE IF NOT EXISTS picking_pickingline (
    id BIGSERIAL PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES picking_pickingtask (id) ON DELETE CASCADE,
    order_line_id BIGINT NOT NULL REFERENCES picking_orderline (id) ON DELETE CASCADE,
    stock_id BIGINT NOT NULL REFERENCES inventory_stock (id) ON DELETE RESTRICT,
    qty_picked NUMERIC(10,2) NOT NULL,
    scanned_oem VARCHAR(64) NOT NULL DEFAULT '',
    CONSTRAINT uniq_picking_line_task_order_stock UNIQUE (task_id, order_line_id, stock_id)
);

CREATE INDEX IF NOT EXISTS picking_pickingline_task_idx ON picking_pickingline (task_id);
CREATE INDEX IF NOT EXISTS picking_pickingline_order_line_idx ON picking_pickingline (order_line_id);

-- =========================
-- reports (ABC-XYZ, Dead Stock, Picking Errors, Analog vs Original)
-- =========================

CREATE TABLE IF NOT EXISTS reports_abcxyzanalysis (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_sales_qty NUMERIC(12,2) NOT NULL DEFAULT 0,
    total_sales_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    abc_class VARCHAR(1) NOT NULL DEFAULT '',
    xyz_class VARCHAR(1) NOT NULL DEFAULT '',
    coefficient_variation NUMERIC(10,4) NULL
);

CREATE INDEX IF NOT EXISTS idx_abcxyz_period ON reports_abcxyzanalysis (period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_abcxyz_class ON reports_abcxyzanalysis (abc_class, xyz_class);

CREATE TABLE IF NOT EXISTS reports_deadstockreport (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    stock_id BIGINT NULL REFERENCES inventory_stock (id) ON DELETE CASCADE,
    qty_available NUMERIC(10,2) NOT NULL DEFAULT 0,
    days_without_movement INTEGER NOT NULL DEFAULT 0,
    last_movement_date DATE NULL,
    estimated_value NUMERIC(12,2) NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dead_stock_days ON reports_deadstockreport (days_without_movement);
CREATE INDEX IF NOT EXISTS idx_dead_stock_calculated ON reports_deadstockreport (calculated_at);

CREATE TABLE IF NOT EXISTS reports_pickingerror (
    id BIGSERIAL PRIMARY KEY,
    order_line_id BIGINT NOT NULL REFERENCES picking_orderline (id) ON DELETE CASCADE,
    picking_line_id BIGINT NULL REFERENCES picking_pickingline (id) ON DELETE SET NULL,
    error_type VARCHAR(32) NOT NULL,
    expected_product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    actual_product_id BIGINT NULL REFERENCES catalog_product (id) ON DELETE SET NULL,
    expected_qty NUMERIC(10,2) NOT NULL,
    actual_qty NUMERIC(10,2) NULL,
    detected_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMPTZ NULL,
    resolved_by_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_picking_error_type ON reports_pickingerror (error_type);
CREATE INDEX IF NOT EXISTS idx_picking_error_detected ON reports_pickingerror (detected_at);
CREATE INDEX IF NOT EXISTS idx_picking_error_resolved ON reports_pickingerror (resolved);

ALTER TABLE reports_pickingerror
    ADD CONSTRAINT IF NOT EXISTS reports_pickingerror_error_type_check
    CHECK (error_type IN ('WRONG_PRODUCT','WRONG_QTY','WRONG_LOCATION','DAMAGED','MISSING'));

CREATE TABLE IF NOT EXISTS reports_analogvsoriginalreport (
    id BIGSERIAL PRIMARY KEY,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    original_product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    analog_product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    original_sales_qty NUMERIC(10,2) NOT NULL DEFAULT 0,
    analog_sales_qty NUMERIC(10,2) NOT NULL DEFAULT 0,
    original_sales_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    analog_sales_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    substitution_rate NUMERIC(5,2) NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uniq_analog_report_period_products UNIQUE (period_start, period_end, original_product_id, analog_product_id)
);

CREATE TABLE IF NOT EXISTS reports_demandforecast (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE CASCADE,
    forecast_date DATE NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    forecasted_qty NUMERIC(12,2) NOT NULL DEFAULT 0,
    confidence_level NUMERIC(5,2) NULL,
    seasonal_factor NUMERIC(5,2) NULL,
    trend_factor NUMERIC(5,2) NULL,
    historical_sales_qty NUMERIC(12,2) NULL,
    historical_period_start DATE NULL,
    historical_period_end DATE NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    calculated_by_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE SET NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_forecast_product_date ON reports_demandforecast (product_id, forecast_date);
CREATE INDEX IF NOT EXISTS idx_forecast_period ON reports_demandforecast (period_start, period_end);

-- =========================
-- catalog (Backorder, Tool)
-- =========================

CREATE TABLE IF NOT EXISTS catalog_backorder (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    order_id BIGINT NOT NULL REFERENCES picking_order (id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES catalog_product (id) ON DELETE RESTRICT,
    qty_ordered NUMERIC(10,2) NOT NULL,
    qty_fulfilled NUMERIC(10,2) NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    expected_arrival_date DATE NULL,
    fulfilled_at TIMESTAMPTZ NULL,
    created_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_backorder_status ON catalog_backorder (status);
CREATE INDEX IF NOT EXISTS idx_backorder_arrival ON catalog_backorder (expected_arrival_date);

ALTER TABLE catalog_backorder
    ADD CONSTRAINT IF NOT EXISTS catalog_backorder_status_check
    CHECK (status IN ('PENDING','PARTIAL','FULFILLED','CANCELLED'));

CREATE TABLE IF NOT EXISTS catalog_tool (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    warehouse_id BIGINT NULL REFERENCES catalog_warehouse (id) ON DELETE RESTRICT,
    tool_type VARCHAR(32) NOT NULL,
    code VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    brand VARCHAR(120) NOT NULL DEFAULT '',
    model VARCHAR(120) NOT NULL DEFAULT '',
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    current_user_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE SET NULL,
    checked_out_at TIMESTAMPTZ NULL,
    expected_return_at TIMESTAMPTZ NULL,
    last_maintenance_date DATE NULL,
    next_maintenance_date DATE NULL,
    maintenance_notes TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tool_warehouse_available ON catalog_tool (warehouse_id, is_available);
CREATE INDEX IF NOT EXISTS idx_tool_type ON catalog_tool (tool_type);

ALTER TABLE catalog_tool
    ADD CONSTRAINT IF NOT EXISTS catalog_tool_tool_type_check
    CHECK (tool_type IN ('FORKLIFT','HAND_TRUCK','SCANNER','PRINTER','OTHER'));

-- =========================
-- tasks (Task, TaskComment)
-- =========================

CREATE TABLE IF NOT EXISTS tasks_task (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    task_type VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    priority VARCHAR(16) NOT NULL DEFAULT 'NORMAL',
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    receiving_id BIGINT NULL REFERENCES receiving_receiving (id) ON DELETE CASCADE,
    inventory_id BIGINT NULL REFERENCES inventory_inventory (id) ON DELETE CASCADE,
    order_id BIGINT NULL REFERENCES picking_order (id) ON DELETE CASCADE,
    picking_task_id BIGINT NULL REFERENCES picking_pickingtask (id) ON DELETE CASCADE,
    assigned_to_id BIGINT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    created_by_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    due_date TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_task_type_status ON tasks_task (task_type, status);
CREATE INDEX IF NOT EXISTS idx_task_assigned_status ON tasks_task (assigned_to_id, status);
CREATE INDEX IF NOT EXISTS idx_task_priority_due ON tasks_task (priority, due_date);

ALTER TABLE tasks_task
    ADD CONSTRAINT IF NOT EXISTS tasks_task_task_type_check
    CHECK (task_type IN ('RECEIVING','INVENTORY','PICKING','SHIPPING','STOCK_MOVEMENT','OTHER'));

ALTER TABLE tasks_task
    ADD CONSTRAINT IF NOT EXISTS tasks_task_status_check
    CHECK (status IN ('PENDING','IN_PROGRESS','COMPLETED','CANCELLED','ON_HOLD'));

ALTER TABLE tasks_task
    ADD CONSTRAINT IF NOT EXISTS tasks_task_priority_check
    CHECK (priority IN ('LOW','NORMAL','HIGH','URGENT'));

CREATE TABLE IF NOT EXISTS tasks_taskcomment (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    task_id BIGINT NOT NULL REFERENCES tasks_task (id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES accounts_user (id) ON DELETE RESTRICT,
    text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS tasks_taskcomment_task_idx ON tasks_taskcomment (task_id);

-- =========================
-- warehouse_3d (WarehouseLayout, StorageObject)
-- =========================

CREATE TABLE IF NOT EXISTS warehouse_3d_warehouselayout (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    warehouse_id BIGINT NOT NULL REFERENCES catalog_warehouse (id) ON DELETE CASCADE,
    floor_points JSONB NOT NULL DEFAULT '[]',
    is_layout_defined BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT warehouse_3d_warehouselayout_warehouse_uniq UNIQUE (warehouse_id)
);

CREATE TABLE IF NOT EXISTS warehouse_3d_storageobject (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    warehouse_id BIGINT NOT NULL REFERENCES catalog_warehouse (id) ON DELETE CASCADE,
    object_type VARCHAR(16) NOT NULL,
    code VARCHAR(64) NOT NULL DEFAULT '',
    name VARCHAR(255) NOT NULL DEFAULT '',
    position_x DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_z DOUBLE PRECISION NOT NULL DEFAULT 0,
    position_y DOUBLE PRECISION NOT NULL DEFAULT 0,
    width DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    depth DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    height DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    rotation_y DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    storage_location_id BIGINT NULL REFERENCES catalog_storagelocation (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_storage_obj_wh_type ON warehouse_3d_storageobject (warehouse_id, object_type);

ALTER TABLE warehouse_3d_storageobject
    ADD CONSTRAINT IF NOT EXISTS warehouse_3d_storageobject_object_type_check
    CHECK (object_type IN ('RACK','SHELF','CELL','FLOOR'));

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
