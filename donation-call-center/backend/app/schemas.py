from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_naive_utc(value: datetime | None) -> datetime | None:
    """The DB stores naive UTC; convert any timezone-aware input."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth / users ----
class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORM):
    id: int
    name: str
    username: str
    role: str
    active: bool
    daily_target: int


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserCreate(BaseModel):
    name: str = Field(min_length=2)
    username: str = Field(min_length=3)
    password: str = Field(min_length=6)
    role: Literal["manager", "agent"] = "agent"
    daily_target: int = 60


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=6)
    active: bool | None = None
    daily_target: int | None = None


# ---- donors ----
class DonorIn(BaseModel):
    name: str = Field(min_length=2)
    phone: str = Field(min_length=6)
    alt_phone: str | None = None
    city: str | None = None
    source: str | None = None
    last_donation_amount: float | None = None
    notes: str | None = None


class DonorUpdate(BaseModel):
    name: str | None = None
    alt_phone: str | None = None
    city: str | None = None
    source: str | None = None
    notes: str | None = None
    do_not_call: bool | None = None
    status: str | None = None  # manager may reopen a donor ("new")


class DonorOut(ORM):
    id: int
    name: str
    phone: str
    alt_phone: str | None
    city: str | None
    source: str | None
    last_donation_amount: float | None
    notes: str | None
    assigned_agent_id: int | None
    agent_name: str | None = None
    status: str
    status_label: str = ""
    attempts: int
    next_action_at: datetime | None
    last_call_at: datetime | None
    pledge_amount: float | None
    pledge_due: datetime | None
    total_donated: float
    do_not_call: bool
    created_at: datetime


class CallIn(BaseModel):
    outcome: str
    notes: str | None = None
    amount: float | None = Field(default=None, ge=0)
    payment_method: str | None = None
    follow_up_at: datetime | None = None
    duration_sec: int | None = Field(default=None, ge=0)

    _utc = field_validator("follow_up_at")(lambda v: to_naive_utc(v))


class CallOut(ORM):
    id: int
    donor_id: int
    donor_name: str = ""
    agent_id: int
    agent_name: str = ""
    outcome: str
    outcome_label: str = ""
    notes: str | None
    amount: float | None
    payment_method: str | None
    follow_up_at: datetime | None
    duration_sec: int | None
    created_at: datetime


class DonorDetail(DonorOut):
    calls: list[CallOut] = []


class Page(BaseModel):
    total: int
    items: list[DonorOut]


# ---- distribution ----
class DonorFilter(BaseModel):
    city: str | None = None
    source: str | None = None
    statuses: list[str] = ["new"]


class AutoDistributeIn(BaseModel):
    agent_ids: list[int] = Field(min_length=1)
    mode: Literal["balanced", "equal", "fixed"] = "balanced"
    per_agent: int | None = Field(default=None, ge=1)  # used by "fixed"
    limit: int | None = Field(default=None, ge=1)
    filter: DonorFilter = DonorFilter()


class AssignIn(BaseModel):
    donor_ids: list[int] = Field(min_length=1)
    agent_id: int


class TransferIn(BaseModel):
    from_agent_id: int
    to_agent_ids: list[int] = Field(min_length=1)  # split evenly across these
    only_open: bool = True


class UnassignIn(BaseModel):
    donor_ids: list[int] = Field(min_length=1)
