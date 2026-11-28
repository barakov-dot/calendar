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
from app.models.demand import Demand, DemandStep
from app.models.extras import Attachment, Signature, Substitution
from app.models.notification import (
    Broadcast,
    Notification,
    NotificationSettings,
    NotificationStatus,
    NotificationType,
)
from app.models.rosstat import RosstatForm
from app.models.task import (
    Audience,
    ChangedBy,
    RecurringReminder,
    ShiftRule,
    Task,
    TaskKind,
    TaskSource,
    TaskStatus,
    WorkDay,
)
from app.models.user import (
    EDITORS,
    MANAGERS,
    AuditLog,
    Invite,
    InviteKind,
    LoginRequest,
    Role,
    User,
)

__all__ = [
    "EDITORS",
    "MANAGERS",
    "Attachment",
    "Audience",
    "AuditLog",
    "Base",
    "Broadcast",
    "ChangedBy",
    "Company",
    "CompanyMember",
    "Demand",
    "DemandStep",
    "EntityType",
    "Invite",
    "InviteKind",
    "LoginRequest",
    "Notification",
    "NotificationSettings",
    "NotificationStatus",
    "NotificationType",
    "Patent",
    "ProfitAdvances",
    "RecurringReminder",
    "Regime",
    "Role",
    "RosstatForm",
    "ShiftRule",
    "Signature",
    "Substitution",
    "Task",
    "TaskKind",
    "TaskSource",
    "TaskStatus",
    "User",
    "WorkDay",
]
