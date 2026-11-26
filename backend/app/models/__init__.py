"""Все модели импортируются здесь, чтобы Alembic видел их в Base.metadata."""

from app.models.base import Base
from app.models.company import (
    Company,
    CompanyMember,
    EntityType,
    Patent,
    ProfitAdvances,
    Regime,
)
from app.models.task import ChangedBy, Task, TaskKind, TaskSource, TaskStatus, WorkDay
from app.models.user import AuditLog, Invite, InviteKind, LoginRequest, Role, User

__all__ = [
    "AuditLog",
    "Base",
    "ChangedBy",
    "Company",
    "CompanyMember",
    "EntityType",
    "Invite",
    "InviteKind",
    "LoginRequest",
    "Patent",
    "ProfitAdvances",
    "Regime",
    "Role",
    "Task",
    "TaskKind",
    "TaskSource",
    "TaskStatus",
    "User",
    "WorkDay",
]
