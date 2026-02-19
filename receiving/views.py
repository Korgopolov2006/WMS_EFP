from __future__ import annotations

from io import BytesIO

from django.contrib import messages
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.constants import Roles
from accounts.permissions import role_required

from .forms import ReceivingForm, ReceivingLineForm
from .models import Receiving, ReceivingLine, ReceivingStatus
from .services import ReceivingService, suggest_storage_location


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_list(request: HttpRequest) -> HttpResponse:
    qs = (
        Receiving.objects.select_related("created_by")
        .annotate(
            total_expected=Coalesce(Sum("lines__qty_expected"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)),
            total_received=Coalesce(Sum("lines__qty_received"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)),
        )
        .all()
    )
    status = (request.GET.get("status") or "").strip()
    if status:
        qs = qs.filter(status=status)
    return render(request, "receiving/list.html", {"items": qs, "status": status, "statuses": ReceivingStatus.choices})


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ReceivingForm(request.POST)
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
        form = ReceivingForm()
    return render(request, "receiving/form.html", {"form": form, "title": "Новая приёмка"})


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_detail(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Receiving, pk=pk)

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

    lines = obj.lines.select_related("product", "storage_location").all()
    total_expected = lines.aggregate(total=Coalesce(Sum("qty_expected"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))["total"]
    total_received = lines.aggregate(total=Coalesce(Sum("qty_received"), Value(0), output_field=DecimalField(max_digits=12, decimal_places=2)))["total"]
    return render(
        request,
        "receiving/detail.html",
        {
            "receiving": obj,
            "lines": lines,
            "total_expected": total_expected,
            "total_received": total_received,
            "lines_count": lines.count(),
            "line_form": ReceivingLineForm(),
            "statuses": ReceivingStatus.choices,
            "user_role": request.user.role,
        },
    )


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_add_line(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Receiving, pk=pk)
    if request.method == "POST":
        form = ReceivingLineForm(request.POST)
        if form.is_valid():
            line: ReceivingLine = form.save(commit=False)
            line.receiving = obj
            if not line.storage_location:
                loc = suggest_storage_location(line.product)
                if loc:
                    line.storage_location = loc
            line.save()
            messages.success(request, "Строка добавлена.")
        else:
            messages.error(request, "Ошибка в строке приёмки.")
    return redirect("receiving_detail", pk=obj.pk)


@role_required(Roles.STOREKEEPER, Roles.ADMIN)
def receiving_pdf(request: HttpRequest, pk: int) -> HttpResponse:
    receiving = get_object_or_404(
        Receiving.objects.select_related("created_by"),
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
