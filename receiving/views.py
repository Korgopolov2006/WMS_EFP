from __future__ import annotations

from datetime import date
from io import BytesIO
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from accounts.constants import Roles
from accounts.permissions import role_required
from catalog.audit import build_product_changes, log_product_change
from catalog.forms import ProductForm
from catalog.models import Product, ProductChangeLog

from .forms import ReceivingForm, ReceivingLineForm, SupplierForm
from .models import Receiving, ReceivingLine, ReceivingStatus, Supplier
from .services import ReceivingService, get_user_warehouses, suggest_storage_location


def _paginate(request: HttpRequest, items, per_page: int = 5):
    paginator = Paginator(items, per_page)
    return paginator.get_page(request.GET.get("page"))


def _style_form_fields(form) -> None:
    for field in form.fields.values():
        widget = field.widget
        input_type = getattr(widget, "input_type", "")
        if input_type in ["checkbox", "radio"]:
            continue
        existing = widget.attrs.get("class", "").strip()
        if "form__input" not in existing.split():
            widget.attrs["class"] = f"{existing} form__input".strip()


def _safe_next_url(request: HttpRequest, fallback_url: str) -> str:
    candidate = (request.GET.get("next") or request.POST.get("next") or "").strip()
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return candidate
    return fallback_url


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_admin_user(user) -> bool:
    return bool(user.is_superuser or user.role == Roles.ADMIN)


def _receiving_visibility_q(user):
    accessible_warehouses = get_user_warehouses(user)
    base_q = Q(warehouse__in=accessible_warehouses)
    if _is_admin_user(user):
        return base_q | Q(warehouse__isnull=True)
    # Legacy-документы без склада временно оставляем видимыми кладовщикам,
    # чтобы они могли зафиксировать склад и продолжить работу.
    return base_q | Q(warehouse__isnull=True)


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    qs = (
        Receiving.objects.select_related("created_by", "warehouse", "warehouse__branch")
        .annotate(
            total_expected=Coalesce(Sum("lines__qty_expected"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)),
            total_received=Coalesce(Sum("lines__qty_received"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)),
        )
        .filter(_receiving_visibility_q(request.user))
        .distinct()
    )
    status = (request.GET.get("status") or "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(number__icontains=q)
            | Q(supplier_name__icontains=q)
            | Q(supplier_doc_no__icontains=q)
            | Q(warehouse__code__icontains=q)
            | Q(warehouse__name__icontains=q)
            | Q(warehouse__branch__code__icontains=q)
            | Q(created_by__username__icontains=q)
        )
    qs = qs.order_by("-id")
    page_obj = _paginate(request, qs, per_page=5)
    return render(
        request,
        "receiving/list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "status": status,
            "statuses": ReceivingStatus.choices,
            "page_obj": page_obj,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReceivingForm(request.POST, user=request.user)
        if form.is_valid():
            obj: Receiving = form.save(commit=False)
            obj.created_by = request.user
            obj.save()
            
            # Создаём задачу на приёмку
            from tasks.services import TaskService
            TaskService.create_receiving_task(obj, request.user)
            
            messages.success(request, f"Приёмка создана: {obj.number}")
            return redirect("receiving_detail", pk=obj.pk)
    else:
        form = ReceivingForm(user=request.user)
        if not form.fields["warehouse"].queryset.exists():
            messages.warning(
                request,
                "У вас нет доступных складов для приёмки. Обратитесь к администратору для назначения доступа.",
            )
    return render(request, "receiving/form.html", {"form": form, "title": "Новая приёмка"})


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def supplier_list(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    qs = Supplier.objects.all()
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    qs = qs.order_by("name")
    page_obj = _paginate(request, qs, per_page=10)
    return render(
        request,
        "receiving/suppliers_list.html",
        {
            "items": page_obj.object_list,
            "q": q,
            "status": status,
            "page_obj": page_obj,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def supplier_create(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(request, reverse("supplier_list"))
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Поставщик создан: {obj.name}")
            return redirect(next_url)
    else:
        form = SupplierForm()
    return render(
        request,
        "receiving/supplier_form.html",
        {
            "form": form,
            "title": "Новый поставщик",
            "next_url": next_url,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_next_supplier_doc(request: HttpRequest) -> JsonResponse:
    supplier_id = (request.GET.get("supplier_id") or "").strip()
    if not supplier_id:
        return JsonResponse({"error": "supplier_id is required"}, status=400)

    supplier = get_object_or_404(Supplier, pk=supplier_id, is_active=True)
    expected_at_raw = (request.GET.get("expected_at") or "").strip()
    expected_at = None
    if expected_at_raw:
        try:
            expected_at = date.fromisoformat(expected_at_raw)
        except ValueError:
            expected_at = None
    doc_no = Receiving.generate_next_supplier_doc_number(
        supplier_code=supplier.code,
        for_date=expected_at or timezone.localdate(),
    )
    return JsonResponse({"supplier_doc_no": doc_no})


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_detail(request: HttpRequest, pk: int) -> HttpResponse:
    accessible_warehouses = get_user_warehouses(request.user)
    obj = get_object_or_404(
        Receiving.objects.select_related("warehouse", "warehouse__branch").filter(_receiving_visibility_q(request.user)).distinct(),
        pk=pk,
    )
    line_q = (request.GET.get("q") or "").strip()
    preset_product_id = (request.GET.get("preset_product_id") or "").strip()

    if request.method == "POST" and "set_warehouse" in request.POST:
        warehouse_id = (request.POST.get("warehouse_id") or "").strip()
        selected_warehouse = accessible_warehouses.filter(pk=warehouse_id).first() if warehouse_id.isdigit() else None
        if not selected_warehouse:
            messages.error(request, "Выберите доступный склад.")
            return redirect("receiving_detail", pk=pk)
        obj.warehouse = selected_warehouse
        obj.save(update_fields=["warehouse"])
        messages.success(request, f"Склад зафиксирован: {selected_warehouse.branch.code}/{selected_warehouse.code}.")
        return redirect("receiving_detail", pk=pk)

    if request.method == "POST" and "change_status" in request.POST:
        new_status = request.POST.get("status", "").strip()
        if new_status in dict(ReceivingStatus.choices):
            old_status = obj.status
            obj.status = new_status
            obj.save(update_fields=["status"])

            if new_status == ReceivingStatus.COMPLETED and old_status != ReceivingStatus.COMPLETED:
                from .services import ReceivingService
                success, msg_list = ReceivingService.complete_receiving(obj)
                if success:
                    for msg in msg_list:
                        messages.success(request, msg)
                else:
                    for msg in msg_list:
                        messages.error(request, msg)
                    # Откатываем статус
                    obj.status = old_status
                    obj.save(update_fields=["status"])

            return redirect("receiving_detail", pk=pk)

    if request.method == "POST" and "receive_all" in request.POST:
        if obj.status not in {ReceivingStatus.DRAFT, ReceivingStatus.IN_PROGRESS}:
            messages.error(request, "Массовое принятие доступно только для черновика или документа в работе.")
            return redirect("receiving_detail", pk=pk)

        updated = obj.lines.exclude(qty_received=F("qty_expected")).update(qty_received=F("qty_expected"))
        if updated:
            messages.success(request, f"Готово: {updated} строк(и) заполнены как полностью принятые.")
        else:
            messages.info(request, "Все строки уже приняты полностью.")
        return redirect("receiving_detail", pk=pk)

    all_lines = obj.lines.select_related("product", "storage_location").order_by("id")
    total_expected = all_lines.aggregate(total=Coalesce(Sum("qty_expected"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))["total"]
    total_received = all_lines.aggregate(total=Coalesce(Sum("qty_received"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))["total"]

    lines = all_lines
    if line_q:
        lines = lines.filter(
            Q(product__internal_sku__icontains=line_q)
            | Q(product__name__icontains=line_q)
            | Q(product__oem_number__icontains=line_q)
            | Q(storage_location__code__icontains=line_q)
            | Q(supplier_sku__icontains=line_q)
        )
    page_obj = _paginate(request, lines, per_page=5)
    line_form_initial = {}
    if preset_product_id.isdigit():
        line_form_initial["product"] = int(preset_product_id)
    line_form = ReceivingLineForm(initial=line_form_initial, user=request.user, warehouse=obj.warehouse)
    locations_available = line_form.fields["storage_location"].queryset.exists()

    next_query = urlencode({"next": reverse("receiving_detail", kwargs={"pk": obj.pk})})
    create_product_url = f"{reverse('receiving_create_product', kwargs={'pk': obj.pk})}?{next_query}"
    return render(
        request,
        "receiving/detail.html",
        {
            "receiving": obj,
            "lines": page_obj.object_list,
            "total_expected": total_expected,
            "total_received": total_received,
            "lines_count": all_lines.count(),
            "line_form": line_form,
            "locations_available": locations_available,
            "statuses": ReceivingStatus.choices,
            "user_role": request.user.role,
            "line_q": line_q,
            "create_product_url": create_product_url,
            "available_warehouses": accessible_warehouses.order_by("branch__code", "code"),
            "page_obj": page_obj,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_add_line(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(
        Receiving.objects.select_related("warehouse").filter(_receiving_visibility_q(request.user)).distinct(),
        pk=pk,
    )
    if request.method == "POST":
        form = ReceivingLineForm(request.POST, user=request.user, warehouse=obj.warehouse)
        if form.is_valid():
            line: ReceivingLine = form.save(commit=False)
            line.receiving = obj
            if not obj.warehouse:
                messages.error(
                    request,
                    "У документа приёмки не указан склад. Укажите склад и повторите добавление строки.",
                )
                return redirect("receiving_detail", pk=obj.pk)
            if not line.storage_location:
                loc = suggest_storage_location(line.product, user=request.user, warehouse=obj.warehouse)
                if loc:
                    line.storage_location = loc
            if not line.storage_location:
                messages.error(
                    request,
                    "Не удалось автоматически подобрать место хранения в доступных вам складах. "
                    "Проверьте настройки доступа к складам и зоны хранения.",
                )
                return redirect("receiving_detail", pk=obj.pk)
            line.save()
            messages.success(request, f"Строка добавлена. Место хранения: {line.storage_location}.")
        else:
            messages.error(request, "Ошибка в строке приёмки.")
    return redirect("receiving_detail", pk=obj.pk)


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_suggest_location(request: HttpRequest, pk: int) -> JsonResponse:
    obj = get_object_or_404(
        Receiving.objects.select_related("warehouse").filter(_receiving_visibility_q(request.user)).distinct(),
        pk=pk,
    )
    product_id_raw = (request.GET.get("product_id") or "").strip()
    if not product_id_raw.isdigit():
        return JsonResponse({"success": False, "error": "product_id is required"}, status=400)

    product = Product.objects.only("id", "packaging_type").filter(pk=int(product_id_raw)).first()
    if not product:
        return JsonResponse({"success": False, "error": "Товар не найден"}, status=404)

    location = suggest_storage_location(product, user=request.user, warehouse=obj.warehouse)
    if not location:
        return JsonResponse({"success": True, "location": None})

    return JsonResponse(
        {
            "success": True,
            "location": {
                "id": location.pk,
                "label": str(location),
                "code": location.code,
            },
        }
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_create_product(request: HttpRequest, pk: int) -> HttpResponse:
    receiving = get_object_or_404(
        Receiving.objects.select_related("warehouse").filter(_receiving_visibility_q(request.user)).distinct(),
        pk=pk,
    )
    next_url = _safe_next_url(request, reverse("receiving_detail", kwargs={"pk": receiving.pk}))

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES)
        _style_form_fields(form)
        if form.is_valid():
            obj = form.save()
            fresh = (
                Product.objects.select_related("brand", "category")
                .prefetch_related("applicability__make")
                .get(pk=obj.pk)
            )
            changes = build_product_changes(
                before=None,
                after=fresh,
                action=ProductChangeLog.Action.CREATE,
            )
            log_product_change(
                product=fresh,
                user=request.user,
                action=ProductChangeLog.Action.CREATE,
                changes=changes,
                source="receiving",
                note=f"Создано из приёмки {receiving.number}",
            )
            messages.success(request, f"Товар создан: {obj.internal_sku} — {obj.name}")
            return redirect(f"{reverse('receiving_detail', kwargs={'pk': receiving.pk})}?{urlencode({'preset_product_id': obj.pk})}")
    else:
        form = ProductForm()
        _style_form_fields(form)

    return render(
        request,
        "receiving/product_form.html",
        {
            "form": form,
            "receiving": receiving,
            "next_url": next_url,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_product_prefill(request: HttpRequest, pk: int) -> JsonResponse:
    # Проверяем доступ к документу приёмки
    get_object_or_404(
        Receiving.objects.filter(_receiving_visibility_q(request.user)).only("id"),
        pk=pk,
    )

    q = (request.GET.get("q") or "").strip()
    try_efp = _as_bool(request.GET.get("try_efp"), default=False)
    async_mode = _as_bool(request.GET.get("async_mode"), default=True)
    task_id = (request.GET.get("task_id") or "").strip()
    if len(q) < 2:
        return JsonResponse({"success": False, "error": "Введите минимум 2 символа"}, status=400)

    # Приоритет: точные совпадения по SKU/OEM/аналогу, затем частичные.
    exact = Product.objects.select_related("brand", "category").prefetch_related("applicability").filter(
        Q(internal_sku__iexact=q) | Q(oem_number__iexact=q) | Q(analog_number__iexact=q)
    ).first()

    product = exact
    if not product:
        product = (
            Product.objects.select_related("brand", "category")
            .prefetch_related("applicability")
            .filter(
                Q(internal_sku__icontains=q)
                | Q(oem_number__icontains=q)
                | Q(analog_number__icontains=q)
                | Q(name__icontains=q)
                | Q(brand__name__icontains=q)
            )
            .order_by("name")
            .first()
        )

    if not product:
        if try_efp:
            try:
                from efp.queue import enqueue_efp_search, get_efp_search_job
                from efp.services import EFPService
            except Exception:
                EFPService = None
                enqueue_efp_search = None
                get_efp_search_job = None

            def build_efp_success_payload(efp_results: list[dict], efp_message: str, *, queue_warning: str = "") -> dict:
                first = efp_results[0]
                payload = {
                    "success": True,
                    "source_type": "efp",
                    "source": {
                        "name": first.get("name") or "",
                        "brand": first.get("brand") or "",
                        "oem_number": q,
                        "detail_url": first.get("detail_url") or "",
                        "manual_url": EFPService.manual_search_url(q),
                    },
                    "prefill": {
                        "name": first.get("name") or "",
                        "oem_number": q,
                        "analog_number": "",
                        "brand_id": "",
                        "category_id": "",
                        "packaging_type": "",
                        "weight_kg": "",
                        "length_cm": "",
                        "width_cm": "",
                        "height_cm": "",
                        "applicability_ids": [],
                    },
                    "warning": "Локальный товар не найден. Данные частично подтянуты из EFP, проверьте и заполните недостающие поля.",
                    "efp_message": efp_message,
                }
                if queue_warning:
                    payload["queue_warning"] = queue_warning
                return payload

            def build_efp_error_payload(efp_message: str, efp_error_code: str, *, queue_warning: str = "") -> tuple[dict, int]:
                status_map = {
                    "validation_error": 400,
                    "not_found": 404,
                    "access_denied": 503,
                    "network_error": 503,
                    "parse_error": 502,
                    "queue_runtime_error": 502,
                    "queue_timeout": 504,
                }
                payload = {
                    "success": False,
                    "error": "Товар в локальной базе не найден. EFP не вернул результат.",
                    "details": efp_message,
                    "error_code": efp_error_code,
                    "manual_url": EFPService.manual_search_url(q) if EFPService is not None else "",
                }
                if queue_warning:
                    payload["queue_warning"] = queue_warning
                return payload, status_map.get(efp_error_code, 502)

            if EFPService is not None:
                if async_mode and enqueue_efp_search and get_efp_search_job:
                    if task_id:
                        job = get_efp_search_job(task_id)
                        if not job:
                            return JsonResponse(
                                {
                                    "success": False,
                                    "error": "Фоновая задача EFP не найдена или устарела.",
                                    "error_code": "task_not_found",
                                    "manual_url": EFPService.manual_search_url(q),
                                },
                                status=404,
                            )

                        status = str(job.get("status") or "")
                        queue_warning = str(job.get("queue_warning") or "")
                        if status in {"queued", "running"}:
                            return JsonResponse(
                                {
                                    "success": False,
                                    "queued": True,
                                    "status": status,
                                    "task_id": task_id,
                                    "backend": job.get("backend") or "",
                                    "message": "Проверяем EFP в фоновом режиме...",
                                    "queue_warning": queue_warning,
                                },
                                status=202,
                            )

                        result = job.get("result") if isinstance(job.get("result"), dict) else {}
                        if status == "done" and result.get("success") and result.get("results"):
                            payload = build_efp_success_payload(
                                efp_results=list(result.get("results") or []),
                                efp_message=str(result.get("message") or ""),
                                queue_warning=queue_warning,
                            )
                            return JsonResponse(payload)

                        payload, error_status = build_efp_error_payload(
                            efp_message=str(result.get("message") or "Ошибка фоновой проверки EFP."),
                            efp_error_code=str(result.get("error_code") or "queue_runtime_error"),
                            queue_warning=queue_warning,
                        )
                        return JsonResponse(payload, status=error_status)

                    try:
                        new_task_id, backend, queue_warning = enqueue_efp_search(q)
                    except Exception as exc:
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Очередь Celery недоступна. Проверьте Redis и worker.",
                                "error_code": "queue_unavailable",
                                "details": str(exc),
                                "manual_url": EFPService.manual_search_url(q),
                            },
                            status=503,
                        )
                    return JsonResponse(
                        {
                            "success": False,
                            "queued": True,
                            "status": "queued",
                            "task_id": new_task_id,
                            "backend": backend,
                            "message": "Запустили фоновую проверку EFP. Ожидаем результат...",
                            "queue_warning": queue_warning,
                        },
                        status=202,
                    )

                efp_success, efp_results, efp_message, efp_error_code = EFPService.search_part(q, use_cache=True)
                if efp_success and efp_results:
                    return JsonResponse(build_efp_success_payload(efp_results=efp_results, efp_message=efp_message))

                payload, error_status = build_efp_error_payload(
                    efp_message=efp_message,
                    efp_error_code=efp_error_code,
                )
                return JsonResponse(payload, status=error_status)

        return JsonResponse({"success": False, "error": "Подходящий товар в номенклатуре не найден"}, status=404)

    payload = {
        "success": True,
        "source_type": "local",
        "source": {
            "id": product.id,
            "internal_sku": product.internal_sku,
            "name": product.name,
            "oem_number": product.oem_number,
        },
        "prefill": {
            "name": product.name or "",
            "oem_number": product.oem_number or "",
            "analog_number": product.analog_number or "",
            "brand_id": product.brand_id,
            "category_id": product.category_id,
            "packaging_type": product.packaging_type or "",
            "weight_kg": str(product.weight_kg) if product.weight_kg is not None else "",
            "length_cm": str(product.length_cm) if product.length_cm is not None else "",
            "width_cm": str(product.width_cm) if product.width_cm is not None else "",
            "height_cm": str(product.height_cm) if product.height_cm is not None else "",
            "applicability_ids": list(product.applicability.values_list("id", flat=True)),
        },
    }
    return JsonResponse(payload)


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    receiving = get_object_or_404(
        Receiving.objects.select_related("created_by", "warehouse", "warehouse__branch").filter(_receiving_visibility_q(request.user)).distinct(),
        pk=pk,
    )
    lines = receiving.lines.select_related("product", "storage_location").all()

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError:
        messages.error(request, "Генерация PDF недоступна: reportlab не установлен.")
        return redirect("receiving_detail", pk=pk)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    font_name = "Helvetica"
    windows_arial = r"C:\Windows\Fonts\arial.ttf"
    try:
        import os

        if os.path.exists(windows_arial):
            pdfmetrics.registerFont(TTFont("ArialUnicode", windows_arial))
            font_name = "ArialUnicode"
    except Exception:
        font_name = "Helvetica"

    y = height - 20 * mm
    pdf.setFont(font_name, 14)
    pdf.drawString(20 * mm, y, "Документ приемки")
    y -= 8 * mm

    pdf.setFont(font_name, 10)
    pdf.drawString(20 * mm, y, f"Номер: {receiving.number}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Поставщик: {receiving.supplier_name}")
    y -= 6 * mm
    if receiving.warehouse:
        warehouse_line = f"Склад: {receiving.warehouse.branch.code}/{receiving.warehouse.code}"
    else:
        warehouse_line = "Склад: —"
    pdf.drawString(20 * mm, y, warehouse_line)
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Статус: {receiving.get_status_display()}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Дата документа: {timezone.localdate().strftime('%d.%m.%Y')}")
    y -= 10 * mm

    pdf.setFont(font_name, 9)
    pdf.drawString(20 * mm, y, "SKU")
    pdf.drawString(55 * mm, y, "Наименование")
    pdf.drawString(120 * mm, y, "Ожид.")
    pdf.drawString(140 * mm, y, "Принято")
    pdf.drawString(165 * mm, y, "Место")
    y -= 4 * mm
    pdf.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    total_expected = 0
    total_received = 0

    for line in lines:
        if y < 20 * mm:
            pdf.showPage()
            pdf.setFont(font_name, 9)
            y = height - 20 * mm
        sku = (line.product.internal_sku or "")[:18]
        product_name = (line.product.name or "")[:34]
        location_code = line.storage_location.code if line.storage_location else "-"

        pdf.drawString(20 * mm, y, sku)
        pdf.drawString(55 * mm, y, product_name)
        pdf.drawRightString(136 * mm, y, str(line.qty_expected))
        pdf.drawRightString(158 * mm, y, str(line.qty_received))
        pdf.drawString(165 * mm, y, location_code[:12])
        y -= 6 * mm

        total_expected += float(line.qty_expected or 0)
        total_received += float(line.qty_received or 0)

    y -= 4 * mm
    pdf.line(20 * mm, y, 190 * mm, y)
    y -= 8 * mm
    pdf.setFont(font_name, 10)
    pdf.drawString(20 * mm, y, f"Итого позиций: {lines.count()}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Итого ожидаемо: {total_expected:.2f}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Итого принято: {total_received:.2f}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="receiving_{receiving.number}.pdf"'
    return response
