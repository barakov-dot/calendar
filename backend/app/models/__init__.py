"""Все модели импортируются здесь, чтобы Alembic видел их в Base.metadata."""

from app.models.base import Base

__all__ = ["Base"]
