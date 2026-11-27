from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    username: str
    role: str
    is_active: bool


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"


class InitDataIn(BaseModel):
    init_data: str = Field(min_length=1, max_length=8192)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=4096)


class WidgetIn(BaseModel):
    """Поля, которые виджет Telegram передаёт странице; подпись покрывает все."""

    model_config = ConfigDict(extra="forbid")

    id: int
    auth_date: int
    hash: str = Field(max_length=128)
    first_name: str | None = Field(None, max_length=256)
    last_name: str | None = Field(None, max_length=256)
    username: str | None = Field(None, max_length=256)
    photo_url: str | None = Field(None, max_length=1024)


class AuthOptionsOut(BaseModel):
    # имя бота для кнопки входа; null — вход через виджет выключен
    widget_bot: str | None


class LoginRequestOut(BaseModel):
    nonce: str
    code: str
    deeplink: str
    expires_at: datetime


class PollOut(BaseModel):
    status: Literal["pending", "ok"]
    tokens: Tokens | None = None


class DevLoginIn(BaseModel):
    user_id: int
