from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Brand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Бренд")),
            ],
            options={"verbose_name": "Бренд", "verbose_name_plural": "Бренды", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Категория")),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="catalog.category",
                        verbose_name="Родительская категория",
                    ),
                ),
            ],
            options={"verbose_name": "Категория", "verbose_name_plural": "Категории", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="StorageZoneType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("code", models.CharField(max_length=32, unique=True, verbose_name="Код")),
                ("name", models.CharField(max_length=120, verbose_name="Название")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
                ("sort_order", models.PositiveIntegerField(default=100, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Тип складской зоны",
                "verbose_name_plural": "Типы складских зон",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="VehicleMake",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("name", models.CharField(max_length=120, unique=True, verbose_name="Марка")),
            ],
            options={"verbose_name": "Марка ТС", "verbose_name_plural": "Марки ТС", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="VehicleModel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("name", models.CharField(max_length=120, verbose_name="Модель")),
                (
                    "make",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="models",
                        to="catalog.vehiclemake",
                        verbose_name="Марка",
                    ),
                ),
            ],
            options={"verbose_name": "Модель ТС", "verbose_name_plural": "Модели ТС", "ordering": ["make__name", "name"]},
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("internal_sku", models.CharField(max_length=64, unique=True, verbose_name="Внутренний артикул")),
                ("name", models.CharField(max_length=255, verbose_name="Наименование")),
                ("oem_number", models.CharField(db_index=True, max_length=64, verbose_name="OEM номер")),
                ("analog_number", models.CharField(blank=True, db_index=True, max_length=64, verbose_name="Номер аналога")),
                (
                    "weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Вес, кг",
                    ),
                ),
                (
                    "length_cm",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Длина, см",
                    ),
                ),
                (
                    "width_cm",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Ширина, см",
                    ),
                ),
                (
                    "height_cm",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=10,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0)],
                        verbose_name="Высота, см",
                    ),
                ),
                (
                    "packaging_type",
                    models.CharField(
                        choices=[("SMALL", "Мелкий"), ("LARGE", "Крупный"), ("PALLET", "Паллетный")],
                        db_index=True,
                        default="SMALL",
                        max_length=16,
                        verbose_name="Тип упаковки",
                    ),
                ),
                ("photo", models.ImageField(blank=True, null=True, upload_to="products/", verbose_name="Фото детали")),
                (
                    "brand",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="catalog.brand",
                        verbose_name="Бренд",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="products",
                        to="catalog.category",
                        verbose_name="Категория",
                    ),
                ),
            ],
            options={
                "verbose_name": "Номенклатура (товар)",
                "verbose_name_plural": "Номенклатура (товары)",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="ProductApplicability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fitments",
                        to="catalog.product",
                        verbose_name="Товар",
                    ),
                ),
                (
                    "vehicle_model",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="fitments",
                        to="catalog.vehiclemodel",
                        verbose_name="Модель ТС",
                    ),
                ),
            ],
            options={"verbose_name": "Применимость товара", "verbose_name_plural": "Применимость товаров"},
        ),
        migrations.CreateModel(
            name="ProductCrossReference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "relation_type",
                    models.CharField(
                        choices=[("ANALOG", "Аналог"), ("OEM", "Оригинал (OEM)"), ("REPLACED_BY", "Заменён на")],
                        db_index=True,
                        max_length=16,
                        verbose_name="Тип связи",
                    ),
                ),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="Комментарий")),
                (
                    "from_product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="xref_from",
                        to="catalog.product",
                        verbose_name="Из товара",
                    ),
                ),
                (
                    "to_product",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="xref_to",
                        to="catalog.product",
                        verbose_name="В товар",
                    ),
                ),
            ],
            options={"verbose_name": "Перекрёстная ссылка", "verbose_name_plural": "Перекрёстные ссылки"},
        ),
        migrations.AddField(
            model_name="product",
            name="applicability",
            field=models.ManyToManyField(
                blank=True,
                related_name="products",
                through="catalog.ProductApplicability",
                to="catalog.vehiclemodel",
                verbose_name="Применимость",
            ),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["oem_number"], name="idx_product_oem"),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["analog_number"], name="idx_product_analog"),
        ),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["brand", "category"], name="idx_product_brand_cat"),
        ),
        migrations.AddConstraint(
            model_name="vehiclemodel",
            constraint=models.UniqueConstraint(fields=("make", "name"), name="uniq_vehicle_model_make_name"),
        ),
        migrations.AddConstraint(
            model_name="productapplicability",
            constraint=models.UniqueConstraint(fields=("product", "vehicle_model"), name="uniq_product_vehicle_model"),
        ),
        migrations.AddConstraint(
            model_name="productcrossreference",
            constraint=models.CheckConstraint(condition=~models.Q(("from_product", models.F("to_product"))), name="chk_xref_not_self"),
        ),
        migrations.AddConstraint(
            model_name="productcrossreference",
            constraint=models.UniqueConstraint(
                fields=("from_product", "to_product", "relation_type"), name="uniq_xref_from_to_type"
            ),
        ),
        migrations.AddIndex(
            model_name="productcrossreference",
            index=models.Index(fields=["from_product", "relation_type"], name="idx_xref_from_type"),
        ),
    ]

