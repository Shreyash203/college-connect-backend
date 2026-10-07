from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class NotificationRead(BaseModel):
    id: int
    message: str
    link: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
