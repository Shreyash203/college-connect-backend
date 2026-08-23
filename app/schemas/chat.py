from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class MessageRead(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    is_read: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ConversationRead(BaseModel):
    id: int
    user1_id: int
    user2_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    other_user_name: Optional[str] = None
    other_user_image: Optional[str] = None
    last_message: Optional[str] = None
    unread_count: int = 0
    other_user_id: int

    class Config:
        from_attributes = True
