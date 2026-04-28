"""
Контекст-процессор: добавляет `notifications_unread` в каждый шаблон,
чтобы topbar мог рисовать badge без отдельного запроса.
"""
from .services import unread_count


def notifications(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"notifications_unread": 0}
    try:
        return {"notifications_unread": unread_count(user)}
    except Exception:
        return {"notifications_unread": 0}
