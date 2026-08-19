from pydantic import BaseModel
from datetime import datetime

class NotificationRead(BaseModel):
    id: int
    message: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
