import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.constants import Roles
from picking.models import Order, OrderPriority
from .forms import ManualTaskForm
from .models import Task, TaskPriority, TaskStatus, TaskType
from .services import TaskService
from .views import next_task


User = get_user_model()


class ManualTaskFormTests(TestCase):
    def test_employee_task_is_assigned_to_self(self):
        user = User.objects.create_user(
            username="picker_self",
            email="picker_self@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )
        form = ManualTaskForm(
            data={
                "task_type": TaskType.PICKING,
                "title": "Проверить ячейку",
                "description": "Сверить остатки",
                "priority": "NORMAL",
            },
            user=user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["assigned_to"], user)

    def test_admin_cannot_assign_task_to_wrong_role(self):
        admin = User.objects.create_user(
            username="task_admin",
            email="task_admin@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN,
            is_superuser=True,
        )
        analyst = User.objects.create_user(
            username="task_analyst",
            email="task_analyst@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.ANALYST,
        )
        form = ManualTaskForm(
            data={
                "task_type": TaskType.RECEIVING,
                "title": "Принять поставку",
                "description": "Документ от начальника",
                "priority": "NORMAL",
                "assigned_to": analyst.pk,
            },
            user=admin,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("assigned_to", form.errors)


class NextTaskTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="next_worker",
            email="next_worker@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        self.other_user = User.objects.create_user(
            username="busy_worker",
            email="busy_worker@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )

    def _request(self):
        request = self.factory.get("/tasks/next/", {"modal": "1"}, HTTP_ACCEPT="application/json")
        request.user = self.user
        return request

    def test_next_task_takes_existing_highest_priority_unassigned_task(self):
        low = Task.objects.create(
            task_type=TaskType.RECEIVING,
            title="Низкий приоритет",
            status=TaskStatus.PENDING,
            priority=TaskPriority.LOW,
            created_by=self.other_user,
        )
        urgent = Task.objects.create(
            task_type=TaskType.RECEIVING,
            title="Срочная задача",
            status=TaskStatus.PENDING,
            priority=TaskPriority.URGENT,
            created_by=self.other_user,
        )

        response = next_task(self._request())

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertTrue(payload["success"])
        self.assertIn(f"/tasks/{urgent.id}/", payload["redirect_url"])
        urgent.refresh_from_db()
        low.refresh_from_db()
        self.assertEqual(urgent.assigned_to, self.user)
        self.assertEqual(urgent.status, TaskStatus.IN_PROGRESS)
        self.assertIsNone(low.assigned_to)

    def test_next_task_ignores_task_assigned_to_another_user(self):
        Task.objects.create(
            task_type=TaskType.RECEIVING,
            title="Уже чужая",
            status=TaskStatus.PENDING,
            priority=TaskPriority.URGENT,
            assigned_to=self.other_user,
            created_by=self.other_user,
        )

        response = next_task(self._request())

        payload = json.loads(response.content.decode("utf-8"))
        self.assertFalse(payload["success"])
        self.assertFalse(payload["has_task"])
        self.assertIn("задач", payload["message"].lower())


class TaskServiceTests(TestCase):
    def test_shipping_task_inherits_order_priority_and_due_date(self):
        manager = User.objects.create_user(
            username="shipping_manager",
            email="shipping_manager@example.com",
            password="Pass1!ABCDEFGH",
            role=Roles.SALES_MANAGER,
        )
        due_date = timezone.now() + timedelta(hours=2)
        order = Order.objects.create(
            number="ORD-SHIP-PRIORITY",
            customer_name="Иван Петров",
            customer_phone="+7 (999) 123-45-67",
            priority=OrderPriority.URGENT,
            shipping_due_at=due_date,
            created_by=manager,
        )

        task = TaskService.create_shipping_task(order, manager)

        self.assertEqual(task.priority, TaskPriority.URGENT)
        self.assertEqual(task.due_date, due_date)
