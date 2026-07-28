from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime

# --- Confession Schemas ---

class ConfessionCreate(BaseModel):
    content: str

class ConfessionRead(BaseModel):
    id: int
    college_domain: str
    content: str
    created_at: datetime
    is_mine: bool = False

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
    is_mine: bool = False

    class Config:
        from_attributes = True
