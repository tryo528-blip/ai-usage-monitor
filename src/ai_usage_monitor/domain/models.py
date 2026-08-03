from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from .enums import ProviderStatus, SourceType


class QuotaWindow(BaseModel):
    key: str
    label: str
    used_percent: float | None = Field(default=None, ge=0, le=100)
    used_value: Decimal | None = None
    limit_value: Decimal | None = None
    remaining_value: Decimal | None = None
    unit: str | None = None
    window_minutes: int | None = Field(default=None, gt=0)
    resets_at: datetime | None = None


class CreditBalance(BaseModel):
    currency: str
    total: Decimal | None = None
    remaining: Decimal | None = None
    used: Decimal | None = None
    granted: Decimal | None = None
    topped_up: Decimal | None = None


class UsageSnapshot(BaseModel):
    provider_id: str
    provider_name: str
    source_type: SourceType
    status: ProviderStatus
    collected_at: datetime
    last_success_at: datetime | None = None
    stale_after_seconds: int = 900
    quota_windows: list[QuotaWindow] = Field(default_factory=list)
    balances: list[CreditBalance] = Field(default_factory=list)
    message: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
