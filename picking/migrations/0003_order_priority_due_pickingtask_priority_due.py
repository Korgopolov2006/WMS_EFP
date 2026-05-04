from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("picking", "0002_order_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="priority",
            field=models.CharField(
                choices=[
                    ("LOW", "Низкая"),
                    ("NORMAL", "Обычная"),
                    ("HIGH", "Важная"),
                    ("URGENT", "Срочная"),
                ],
                db_index=True,
                default="NORMAL",
                max_length=16,
                verbose_name="Важность заказа",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="shipping_due_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Дата и время, к которым заказ желательно отгрузить.",
                null=True,
                verbose_name="Срок отгрузки",
            ),
        ),
        migrations.AddField(
            model_name="pickingtask",
            name="due_date",
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Срок выполнения"),
        ),
        migrations.AddField(
            model_name="pickingtask",
            name="priority",
            field=models.CharField(
                choices=[
                    ("LOW", "Низкая"),
                    ("NORMAL", "Обычная"),
                    ("HIGH", "Важная"),
                    ("URGENT", "Срочная"),
                ],
                db_index=True,
                default="NORMAL",
                max_length=16,
                verbose_name="Важность",
            ),
        ),
    ]
