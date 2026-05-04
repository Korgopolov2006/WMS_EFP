from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("picking", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="note",
            field=models.TextField(
                blank=True,
                help_text="Важные нюансы для сборщика или сотрудника отгрузки.",
                verbose_name="Комментарий к заказу",
            ),
        ),
    ]
