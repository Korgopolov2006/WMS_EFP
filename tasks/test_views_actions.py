"""
Тесты пользовательских сценариев в tasks views.

Покрывает:
 * task_create — создание задачи
 * task_list — фильтры
 * task_detail — start/complete с матрицей ролей
 * next_task — взятие следующей задачи
 * tasks_monitoring и monitoring_api
"""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.constants import Roles
from receiving.models import Receiving, ReceivingStatus
from catalog.models import Branch, Warehouse

from tasks.models import Task, TaskPriority, TaskStatus, TaskType


User = get_user_model()


class TasksViewsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="t_admin", email="ta@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.ADMIN, is_superuser=True,
        )
        cls.storekeeper = User.objects.create_user(
            username="t_stk", email="ts@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.STOREKEEPER,
        )
        cls.picker = User.objects.create_user(
            username="t_pck", email="tp@t.ru",
            password="Pass1!ABCDEFGH",
            role=Roles.SMALL_PARTS_PICKER,
        )

        branch = Branch.objects.create(code="BR1", name="Главный")
        cls.warehouse = Warehouse.objects.create(branch=branch, code="WH1", name="WH1")

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c


# ════════════════════════════════════════════════════════════════════
# task_list
# ════════════════════════════════════════════════════════════════════
class TaskListTests(TasksViewsBase):
    def test_list_renders_for_admin(self):
        Task.objects.create(
            task_type=TaskType.OTHER, title="t1",
            created_by=self.admin,
        )
        client = self._client(self.admin)
        response = client.get(reverse("task_list"))
        self.assertEqual(response.status_code, 200)

    def test_list_filter_by_status(self):
        client = self._client(self.admin)
        response = client.get(reverse("task_list"), {"status": "PENDING"})
        self.assertEqual(response.status_code, 200)

    def test_list_filter_my_tasks(self):
        Task.objects.create(
            task_type=TaskType.OTHER, title="мой",
            assigned_to=self.storekeeper, created_by=self.admin,
        )
        client = self._client(self.storekeeper)
        response = client.get(reverse("task_list"), {"my_tasks": "1"})
        self.assertEqual(response.status_code, 200)

    def test_list_search(self):
        Task.objects.create(
            task_type=TaskType.OTHER, title="Уникальный заголовок",
            created_by=self.admin,
        )
        client = self._client(self.admin)
        response = client.get(reverse("task_list"), {"q": "Уникальный"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# task_create
# ════════════════════════════════════════════════════════════════════
class TaskCreateTests(TasksViewsBase):
    def test_get_form(self):
        client = self._client(self.admin)
        response = client.get(reverse("task_create"))
        self.assertEqual(response.status_code, 200)

    def test_admin_creates_task_for_employee(self):
        client = self._client(self.admin)
        response = client.post(reverse("task_create"), {
            "task_type": TaskType.OTHER,
            "title": "Поручение через UI",
            "description": "...",
            "priority": TaskPriority.NORMAL,
            "assigned_to": str(self.storekeeper.pk),
        })
        self.assertIn(response.status_code, (200, 302))
        task = Task.objects.filter(title="Поручение через UI").first()
        self.assertIsNotNone(task)
        self.assertEqual(task.assigned_to, self.storekeeper)

    def test_employee_creates_task_for_self(self):
        client = self._client(self.storekeeper)
        client.post(reverse("task_create"), {
            "task_type": TaskType.OTHER,
            "title": "Сам себе",
            "description": "...",
            "priority": TaskPriority.LOW,
        })
        task = Task.objects.filter(title="Сам себе").first()
        self.assertIsNotNone(task)
        # обычный пользователь создаёт на себя
        self.assertEqual(task.assigned_to, self.storekeeper)


# ════════════════════════════════════════════════════════════════════
# task_detail — start / complete
# ════════════════════════════════════════════════════════════════════
class TaskDetailActionsTests(TasksViewsBase):
    def test_start_action_assigns_user(self):
        # admin + OTHER (без требований к документу-источнику)
        task = Task.objects.create(
            task_type=TaskType.OTHER, title="t",
            status=TaskStatus.PENDING, created_by=self.admin,
        )
        client = self._client(self.admin)
        client.post(
            reverse("task_detail", args=[task.id]),
            {"action": "start"},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.assigned_to, self.admin)

    def test_complete_generic_task(self):
        # OTHER доступен только админам, для storekeeper берём RECEIVING
        task = Task.objects.create(
            task_type=TaskType.OTHER, title="t",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=self.admin, created_by=self.admin,
        )
        client = self._client(self.admin)
        client.post(
            reverse("task_detail", args=[task.id]),
            {"action": "complete"},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_complete_receiving_task_requires_doc_completion(self):
        recv = Receiving.objects.create(
            supplier_name="ACME", warehouse=self.warehouse,
            created_by=self.admin,
        )
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="recv",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=self.storekeeper, receiving=recv,
            created_by=self.admin,
        )
        client = self._client(self.storekeeper)
        client.post(
            reverse("task_detail", args=[task.id]),
            {"action": "complete"},
        )
        task.refresh_from_db()
        # Документ не завершён → задача не закрыта
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)

    def test_get_task_detail(self):
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="t",
            assigned_to=self.storekeeper, created_by=self.admin,
        )
        client = self._client(self.storekeeper)
        response = client.get(reverse("task_detail", args=[task.id]))
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# next_task
# ════════════════════════════════════════════════════════════════════
class NextTaskTests(TasksViewsBase):
    def test_redirect_to_in_progress_task_if_exists(self):
        # Уже взятая задача — у storekeeper тип должен быть из его роли (RECEIVING)
        task = Task.objects.create(
            task_type=TaskType.RECEIVING, title="moя",
            status=TaskStatus.IN_PROGRESS,
            assigned_to=self.storekeeper, created_by=self.admin,
        )
        client = self._client(self.storekeeper)
        response = client.get(reverse("next_task"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(f"/tasks/{task.id}/", response["Location"])

    def test_returns_json_when_requested(self):
        Task.objects.create(
            task_type=TaskType.OTHER, title="доступная",
            status=TaskStatus.PENDING, created_by=self.admin,
        )
        client = self._client(self.storekeeper)
        response = client.get(reverse("next_task"), {"modal": "1"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertIn("success", data)

    def test_returns_no_task_message(self):
        client = self._client(self.picker)
        # для пикера нет задач PICKING
        response = client.get(reverse("next_task"), {"modal": "1"})
        self.assertEqual(response.status_code, 200)


# ════════════════════════════════════════════════════════════════════
# tasks_monitoring
# ════════════════════════════════════════════════════════════════════
class TasksMonitoringTests(TasksViewsBase):
    def test_monitoring_page_renders(self):
        client = self._client(self.admin)
        response = client.get(reverse("tasks_monitoring"))
        self.assertEqual(response.status_code, 200)

    def test_monitoring_api_returns_json(self):
        client = self._client(self.admin)
        response = client.get(reverse("tasks_monitoring_api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
