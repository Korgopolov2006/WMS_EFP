"""
Корневой conftest.py для pytest + Django.
"""
import pytest


@pytest.fixture(autouse=True)
def override_email_backend(settings):
    """EMAIL — всегда in-memory в тестах."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
