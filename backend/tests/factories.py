from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models import Role, User
from tests.conftest import JWT_SECRET


async def make_user(
    db: AsyncSession, telegram_id: int, role: Role = Role.ACCOUNTANT, **fields
) -> User:
    fields.setdefault("pd_consent_at", datetime.now(UTC))
    user = User(telegram_id=telegram_id, role=role, **fields)
    db.add(user)
    await db.commit()
    return user


def auth(user: User) -> dict[str, str]:
    token = security.create_token(user.id, "access", JWT_SECRET)
    return {"Authorization": f"Bearer {token}"}
