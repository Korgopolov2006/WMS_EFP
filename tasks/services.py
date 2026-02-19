"""
Сервисы для модуля tasks.
Автоматическое создание и назначение задач по ролям.
"""

from __future__ import annotations

from django.utils import timezone

from accounts.constants import Roles
from .models import Task, TaskStatus, TaskType, TaskPriority


class TaskService:
    """Сервис для управления задачами."""

    @staticmethod
    def get_tasks_for_user(user) -> list[Task]:
        """
        Возвращает задачи, доступные пользователю в зависимости от его роли.
        
        Args:
            user: Пользователь
            
        Returns:
            QuerySet задач
        """
        if user.is_superuser or user.role == Roles.ADMIN:
            # Админ видит все задачи
            return Task.objects.all()
        
        # Фильтруем по типу задачи в зависимости от роли
        task_types = TaskService._get_task_types_for_role(user.role)
        
        return Task.objects.filter(task_type__in=task_types)

    @staticmethod
    def _get_task_types_for_role(role: str) -> list[str]:
        """Возвращает типы задач, доступные для роли."""
        role_task_mapping = {
            Roles.STOREKEEPER: [
                TaskType.RECEIVING,
                TaskType.INVENTORY,
                TaskType.STOCK_MOVEMENT,
                TaskType.PICKING,  # Кладовщик может подбирать
            ],
            Roles.SMALL_PARTS_PICKER: [
                TaskType.PICKING,
            ],
            Roles.LOADER: [
                TaskType.SHIPPING,
                TaskType.PICKING,  # Только для напольных зон
            ],
            Roles.SALES_MANAGER: [
                # Менеджер не работает с задачами склада напрямую
            ],
            Roles.ANALYST: [
                # Аналитик не работает с задачами
            ],
            Roles.INTEGRATION: [
                # Интеграции не работают с задачами
            ],
        }
        
        return role_task_mapping.get(role, [])

    @staticmethod
    def create_receiving_task(receiving, created_by) -> Task:
        """Создаёт задачу на приёмку."""
        return Task.objects.create(
            task_type=TaskType.RECEIVING,
            title=f"Приёмка {receiving.number}",
            description=f"Принять товар от поставщика {receiving.supplier_name}",
            receiving=receiving,
            status=TaskStatus.PENDING,
            priority=TaskPriority.NORMAL,
            created_by=created_by,
        )

    @staticmethod
    def create_inventory_task(inventory, created_by) -> Task:
        """Создаёт задачу на инвентаризацию."""
        zone_name = inventory.zone.name if inventory.zone else "всего склада"
        return Task.objects.create(
            task_type=TaskType.INVENTORY,
            title=f"Инвентаризация {inventory.number}",
            description=f"Провести инвентаризацию зоны {zone_name}",
            inventory=inventory,
            status=TaskStatus.PENDING,
            priority=TaskPriority.NORMAL,
            created_by=created_by,
        )

    @staticmethod
    def create_shipping_task(order, created_by) -> Task:
        """Создаёт задачу на отгрузку."""
        return Task.objects.create(
            task_type=TaskType.SHIPPING,
            title=f"Отгрузка заказа {order.number}",
            description=f"Отгрузить заказ клиенту {order.customer_name}",
            order=order,
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            created_by=created_by,
        )

    @staticmethod
    def assign_task_to_user(task: Task, user) -> bool:
        """
        Назначает задачу пользователю, если это разрешено его ролью.
        
        Returns:
            True, если назначение успешно
        """
        if not task.can_be_assigned_to(user):
            return False
        
        task.assigned_to = user
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = timezone.now()
        task.save(update_fields=["assigned_to", "status", "started_at"])
        
        return True

    @staticmethod
    def complete_task(task: Task, user) -> bool:
        """Завершает задачу."""
        if task.assigned_to != user and not user.is_superuser:
            return False
        
        task.status = TaskStatus.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=["status", "completed_at"])
        
        return True
