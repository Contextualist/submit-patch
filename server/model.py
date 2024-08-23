import enum
import uuid
from dataclasses import dataclass
from datetime import datetime


class PatchState(enum.IntEnum):
    Pending = 0
    Accept = 1
    Rejected = 2
    Outdated = 3


@dataclass(frozen=True, kw_only=True, slots=True)
class PatchBase:
    id: uuid.UUID
    state: int
    from_user_id: int
    wiki_user_id: int
    reason: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    reject_reason: str


@dataclass(frozen=True, kw_only=True, slots=True)
class Patch(PatchBase):
    subject_id: int
    subject_type: int

    name: str | None
    original_name: str
    edited_name: str | None
    infobox: str | None
    original_infobox: str | None
    edited_infobox: str | None
    summary: str | None
    original_summary: str | None
    edited_summary: str | None
    nsfw: bool | None
    edited_nsfw: bool | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    reject_reason: str
    edited_reason: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class EpisodePatch(PatchBase):
    episode_id: int

    original_name: str
    name: str | None
    original_name_cn: str
    name_cn: str | None
    original_duration: str
    duration: str | None
    original_airdate: str
    airdate: str | None
    original_description: str
    description: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Wiki:
    name: str
    infobox: str
    summary: str
    nsfw: bool
