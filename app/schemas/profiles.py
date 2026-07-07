from typing import List, Optional

from pydantic import BaseModel


class ProfileCreate(BaseModel):
    display_name: Optional[str]
    department: Optional[str]
    year: Optional[str]
    bio: Optional[str]
    interests: List[str]


class ProfileRead(BaseModel):
    image_url: Optional[str] = None
    id: int
    user_id: int
    display_name: Optional[str]
    department: Optional[str]
    year: Optional[str]
    bio: Optional[str]
    interests: List[str]
