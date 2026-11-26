from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role, User


async def get_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    return await db.scalar(select(User).where(User.telegram_id == telegram_id))


def can_sign_in(user: User | None) -> bool:
    """Вход разрешён только активным пользователям, принявшим согласие на обработку ПДн."""
    return user is not None and user.is_active and user.pd_consent_at is not None


async def ensure_admin(db: AsyncSession, telegram_id: int) -> None:
    """Создаёт первого администратора из ADMIN_TELEGRAM_ID. Повторный вызов безопасен."""
    await db.execute(
        insert(User)
        .values(telegram_id=telegram_id, role=Role.ADMIN)
        .on_conflict_do_update(
            index_elements=[User.telegram_id], set_={"role": Role.ADMIN, "is_active": True}
        )
    )
    await db.commit()
