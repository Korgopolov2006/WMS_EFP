# Статус разработки WMS-системы

## 📊 Анализ текущего состояния проекта

### ✅ Реализованные модули

#### 1. **accounts** — Пользователи и роли
- ✅ Модель User с ролями (ADMIN, STOREKEEPER, SMALL_PARTS_PICKER, LOADER, SALES_MANAGER, ANALYST, INTEGRATION)
- ✅ Связь с филиалами (branches)
- ✅ Система доступа к складам (WarehouseAccess)
- ✅ Разграничение прав по ролям

#### 2. **catalog** — Справочники (МОДУЛЬ 1)
- ✅ Branch (филиалы)
- ✅ Warehouse (склады)
- ✅ WarehouseAccess (доступы)
- ✅ Brand (бренды)
- ✅ Category (категории, иерархические)
- ✅ VehicleMake/VehicleModel (марки и модели ТС)
- ✅ StorageZoneType/StorageZone (типы и зоны хранения)
- ✅ StorageLocation (места хранения)
- ✅ Product (номенклатура)
  - ✅ OEM номер, аналог
  - ✅ Габариты, вес
  - ✅ Тип упаковки (SMALL, LARGE, PALLET)
  - ✅ Фото
- ✅ ProductApplicability (применимость)
- ✅ ProductCrossReference (OEM ↔ аналоги)

**Статус:** ✅ Полностью реализован

#### 3. **receiving** — Приёмка (МОДУЛЬ 2)
- ✅ Receiving (документ приёмки)
- ✅ ReceivingLine (строки приёмки)
- ✅ ReceivingSerial (серийные номера)
- ✅ Статусы: DRAFT, IN_PROGRESS, COMPLETED, CANCELLED

**Статус:** ✅ Базовая структура готова, нужна доработка UI

#### 4. **inventory** — Хранение и инвентаризация (МОДУЛЬ 3)
- ✅ Stock (остатки)
  - ✅ qty_available, qty_reserved
  - ✅ batch_no, expiry_date
- ✅ Inventory (инвентаризация)
- ✅ InventoryLine (строки инвентаризации)
- ✅ Статусы: DRAFT, IN_PROGRESS, COMPLETED, CANCELLED

**Статус:** ✅ Базовая структура готова, нужна доработка логики размещения

#### 5. **picking** — Комплектация и отгрузка (МОДУЛЬ 4)
- ✅ Order (заказы)
  - ✅ Статусы: DRAFT, CONFIRMED, IN_PICKING, PICKED, RESERVED, SHIPPED, CANCELLED
  - ✅ Источники: MANUAL, POS, ONLINE, API
- ✅ OrderLine (строки заказа)
- ✅ PickingTask (задачи подбора)
  - ✅ Разделение по зонам (zone_type_code)
- ✅ PickingLine (строки подбора)
  - ✅ Сканирование OEM

**Статус:** ✅ Базовая структура готова, нужна доработка маршрутизации

#### 6. **tasks** — Управление задачами (МОДУЛЬ 5)
- ✅ Мониторинг задач (views)
- ✅ API для мониторинга
- ✅ Task (универсальная модель задач) — **ДОБАВЛЕНО**
- ✅ TaskComment (комментарии к задачам) — **ДОБАВЛЕНО**
- ✅ Связи с Receiving, Inventory, Order, PickingTask

**Статус:** ✅ Полностью реализован

#### 7. **reports** — Отчётность и аналитика (МОДУЛЬ 6)
- ✅ ABCXYZAnalysis (ABC-XYZ анализ)
- ✅ DeadStockReport (мёртвые остатки)
- ✅ PickingError (ошибки подбора)
- ✅ AnalogVsOriginalReport (аналоги vs оригиналы)
- ✅ DemandForecast (прогноз спроса) — **ДОБАВЛЕНО**

**Статус:** ✅ Полностью реализован

#### 8. **warehouse_3d** — 3D-визуализация склада
- ✅ WarehouseLayout (геометрия склада)
- ✅ StorageObject (3D-объекты: стеллажи, полки, ячейки, напольные зоны)
- ✅ Интеграция с Three.js
- ✅ Управление через UI
- ✅ Связь с StorageLocation

**Статус:** ✅ Полностью реализован и работает

#### 9. **api** — Интеграции (МОДУЛЬ 7)
- ✅ APIToken (токены для API)
- ❌ Нет интеграции с 1С:Розница
- ❌ Нет интеграции с TecDoc
- ❌ Нет онлайн-витрины

**Статус:** ⚠️ Базовая структура готова, нужны интеграции

### ✅ Дополнительные функции (МОДУЛЬ 8)

#### Реализовано:
- ✅ Backorder (модель создана в `catalog/models_additional.py`)
- ✅ Tool (модель для учёта инструмента создана)
- ✅ Контроль сроков годности (поле `expiry_date` в Stock, логику можно добавить в сервисы)

#### Нужно доработать:
- ⚠️ Логика автоматического создания Backorder при отсутствии товара
- ⚠️ Сервис контроля сроков годности (уведомления, отчёты)
- ⚠️ UI для управления инструментами

### 📋 Что нужно доработать

#### 1. **schema.sql** — КРИТИЧНО
- ❌ Отсутствуют таблицы:
  - `inventory_stock`
  - `inventory_inventory`
  - `inventory_inventoryline`
  - `picking_order`
  - `picking_orderline`
  - `picking_pickingtask`
  - `picking_pickingline`
  - `reports_abcxyzanalysis`
  - `reports_deadstockreport`
  - `reports_pickingerror`
  - `reports_analogvsoriginalreport`
  - `warehouse_3d_warehouselayout`
  - `warehouse_3d_storageobject`
  - `catalog_branch`
  - `catalog_warehouse`
  - `catalog_warehouseaccess`
  - `accounts_user_branches` (M2M)

**Действие:** Обновить команду `rebuild_schema_sql` или вручную дополнить schema.sql

#### 2. **tasks** — Модели задач
- ❌ Создать модель Task для управления задачами
- ❌ Связь с заказами, инвентаризацией, приёмкой

#### 3. **reports** — Прогноз спроса
- ❌ Создать модель DemandForecast
- ❌ Реализовать алгоритм прогнозирования

#### 4. **api** — Интеграции
- ❌ 1С:Розница (синхронизация товаров, заказов)
- ❌ TecDoc (импорт каталога)
- ❌ Онлайн-витрина (API для отображения остатков)

#### 5. **Дополнительные функции**
- ❌ Backorder (модель + логика)
- ❌ Контроль сроков годности (сервис + уведомления)
- ❌ Учёт инструмента (модель Tool)

### 🎯 План дальнейшей разработки

1. **Обновить schema.sql** — добавить все недостающие таблицы
2. **Доработать tasks** — создать модели и полный функционал
3. **Доработать reports** — добавить прогноз спроса
4. **Реализовать интеграции** — 1С, TecDoc, онлайн-витрина
5. **Дополнительные функции** — Backorder, контроль сроков, инструмент
