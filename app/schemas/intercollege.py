from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from datetime import datetime, timezone

# --- Confession Schemas ---

class ConfessionCreate(BaseModel):
    content: str
    scope: str = 'global'  # 'global' or 'college'

class ConfessionRead(BaseModel):
    id: int
    college_domain: str
    content: str
    scope: str = 'global'
    created_at: datetime
    is_mine: bool = False
    likes_count: int = 0
    has_liked: bool = False

    class Config:
        from_attributes = True

# --- Launchpad Schemas ---

class StudentAppCreate(BaseModel):
    app_name: str
    description: str
    app_url: Optional[str] = None

class StudentAppRead(BaseModel):
    id: int
    app_name: str
    description: str
    app_url: Optional[str] = None
    college_domain: str
    created_at: datetime
    user_id: int
    email: Optional[str] = None
    is_mine: bool = False

    class Config:
        from_attributes = True


# --- Campus Event Schemas ---

class CampusEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=1500)
    event_date: datetime
    venue: str = Field(min_length=1, max_length=255)
    category: str = Field(default="General", min_length=1, max_length=50)
    scope: Literal["college", "global"] = "college"

    @field_validator("title", "description", "venue", "category")
    @classmethod
    def strip_event_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank.")
        return value

    @field_validator("event_date")
    @classmethod
    def normalize_event_date(cls, value: datetime) -> datetime:
        if value.utcoffset() is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class EventRsvpRequest(BaseModel):
    status: Literal["going", "interested"] = "going"


class CampusEventRead(BaseModel):
    id: int
    user_id: int
    organizer_name: Optional[str] = None
    organizer_email: Optional[str] = None
    organizer_department: Optional[str] = None
    organizer_year: Optional[str] = None
    title: str
    description: str
    event_date: datetime
    venue: str
    category: str = "General"
    scope: str = "college"
    college_domain: str
    created_at: datetime
    rsvp_count: int = 0
    going_count: int = 0
    interested_count: int = 0
    has_rsvped: bool = False
    rsvp_status: Optional[Literal["going", "interested"]] = None
    is_mine: bool = False

    class Config:
        from_attributes = True
