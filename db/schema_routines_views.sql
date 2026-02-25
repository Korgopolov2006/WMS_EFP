BEGIN;

CREATE OR REPLACE FUNCTION public.fn_set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE PROCEDURE public.sp_install_updated_at_triggers()
LANGUAGE plpgsql
AS $$
DECLARE
    rec record;
BEGIN
    FOR rec IN
        SELECT table_schema, table_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name = 'updated_at'
        GROUP BY table_schema, table_name
        ORDER BY table_schema, table_name
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_set_updated_at ON %I.%I;',
            rec.table_schema,
            rec.table_name
        );

        EXECUTE format(
            'CREATE TRIGGER trg_set_updated_at BEFORE UPDATE ON %I.%I FOR EACH ROW EXECUTE FUNCTION public.fn_set_updated_at();',
            rec.table_schema,
            rec.table_name
        );
    END LOOP;
END;
$$;

CALL public.sp_install_updated_at_triggers();

CREATE OR REPLACE FUNCTION public.fn_inventoryline_sync_discrepancy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.qty_actual IS NULL THEN
        NEW.discrepancy := COALESCE(NEW.discrepancy, 0);
    ELSE
        NEW.discrepancy := COALESCE(NEW.qty_actual, 0) - COALESCE(NEW.qty_book, 0);
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_inventoryline_sync_discrepancy ON public.inventory_inventoryline;
CREATE TRIGGER trg_inventoryline_sync_discrepancy
BEFORE INSERT OR UPDATE ON public.inventory_inventoryline
FOR EACH ROW
EXECUTE FUNCTION public.fn_inventoryline_sync_discrepancy();

CREATE OR REPLACE FUNCTION public.fn_order_status_timestamps()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'CONFIRMED' AND NEW.confirmed_at IS NULL THEN
        NEW.confirmed_at := NOW();
    END IF;

    IF NEW.status IN ('PICKED', 'RESERVED') AND NEW.picked_at IS NULL THEN
        NEW.picked_at := NOW();
    END IF;

    IF NEW.status = 'SHIPPED' AND NEW.shipped_at IS NULL THEN
        NEW.shipped_at := NOW();
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_order_status_timestamps ON public.picking_order;
CREATE TRIGGER trg_order_status_timestamps
BEFORE INSERT OR UPDATE ON public.picking_order
FOR EACH ROW
EXECUTE FUNCTION public.fn_order_status_timestamps();

CREATE OR REPLACE FUNCTION public.fn_receiving_completed_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'COMPLETED' AND NEW.completed_at IS NULL THEN
        NEW.completed_at := NOW();
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_receiving_completed_at ON public.receiving_receiving;
CREATE TRIGGER trg_receiving_completed_at
BEFORE INSERT OR UPDATE ON public.receiving_receiving
FOR EACH ROW
EXECUTE FUNCTION public.fn_receiving_completed_at();

CREATE OR REPLACE FUNCTION public.fn_task_status_timestamps()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.status = 'IN_PROGRESS' AND NEW.started_at IS NULL THEN
        NEW.started_at := NOW();
    END IF;

    IF NEW.status = 'COMPLETED' THEN
        IF NEW.started_at IS NULL THEN
            NEW.started_at := NOW();
        END IF;
        IF NEW.completed_at IS NULL THEN
            NEW.completed_at := NOW();
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_task_status_timestamps ON public.tasks_task;
CREATE TRIGGER trg_task_status_timestamps
BEFORE INSERT OR UPDATE ON public.tasks_task
FOR EACH ROW
EXECUTE FUNCTION public.fn_task_status_timestamps();

CREATE OR REPLACE PROCEDURE public.sp_recalculate_operational_fields()
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE public.inventory_inventoryline
    SET discrepancy = COALESCE(qty_actual, 0) - COALESCE(qty_book, 0);

    UPDATE public.receiving_receiving
    SET completed_at = NOW()
    WHERE status = 'COMPLETED' AND completed_at IS NULL;

    UPDATE public.picking_order
    SET confirmed_at = NOW()
    WHERE status = 'CONFIRMED' AND confirmed_at IS NULL;

    UPDATE public.picking_order
    SET picked_at = NOW()
    WHERE status IN ('PICKED', 'RESERVED') AND picked_at IS NULL;

    UPDATE public.picking_order
    SET shipped_at = NOW()
    WHERE status = 'SHIPPED' AND shipped_at IS NULL;

    UPDATE public.tasks_task
    SET started_at = NOW()
    WHERE status = 'IN_PROGRESS' AND started_at IS NULL;

    UPDATE public.tasks_task
    SET completed_at = NOW()
    WHERE status = 'COMPLETED' AND completed_at IS NULL;
END;
$$;

CREATE OR REPLACE VIEW public.v_order_progress AS
SELECT
    o.id,
    o.number,
    o.status,
    o.customer_name,
    o.customer_phone,
    o.created_at,
    COUNT(ol.id) AS lines_count,
    COALESCE(SUM(ol.qty_ordered), 0) AS qty_ordered_total,
    COALESCE(SUM(ol.qty_picked), 0) AS qty_picked_total,
    COALESCE(SUM(ol.qty_ordered - ol.qty_picked), 0) AS qty_remaining_total
FROM public.picking_order o
LEFT JOIN public.picking_orderline ol ON ol.order_id = o.id
GROUP BY o.id, o.number, o.status, o.customer_name, o.customer_phone, o.created_at;

CREATE OR REPLACE VIEW public.v_stock_snapshot AS
SELECT
    s.id,
    p.id AS product_id,
    p.internal_sku,
    p.name AS product_name,
    sl.id AS storage_location_id,
    sl.code AS storage_location_code,
    z.id AS zone_id,
    z.code AS zone_code,
    z.name AS zone_name,
    s.batch_no,
    s.expiry_date,
    s.qty_available,
    s.qty_reserved,
    (s.qty_available + s.qty_reserved) AS qty_total
FROM public.inventory_stock s
JOIN public.catalog_product p ON p.id = s.product_id
JOIN public.catalog_storagelocation sl ON sl.id = s.storage_location_id
JOIN public.catalog_storagezone z ON z.id = sl.zone_id;

CREATE OR REPLACE VIEW public.v_task_operational AS
SELECT
    t.id,
    t.task_type,
    t.status,
    t.priority,
    t.title,
    t.assigned_to_id,
    au.username AS assigned_to_username,
    t.created_by_id,
    cu.username AS created_by_username,
    t.created_at,
    t.started_at,
    t.completed_at,
    t.due_date,
    t.order_id,
    o.number AS order_number,
    t.receiving_id,
    r.number AS receiving_number,
    t.inventory_id,
    i.number AS inventory_number,
    t.picking_task_id
FROM public.tasks_task t
LEFT JOIN public.accounts_user au ON au.id = t.assigned_to_id
LEFT JOIN public.accounts_user cu ON cu.id = t.created_by_id
LEFT JOIN public.picking_order o ON o.id = t.order_id
LEFT JOIN public.receiving_receiving r ON r.id = t.receiving_id
LEFT JOIN public.inventory_inventory i ON i.id = t.inventory_id;

COMMIT;
