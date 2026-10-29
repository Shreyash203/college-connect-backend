from typing import List, Optional

from pydantic import BaseModel


class ProfileCreate(BaseModel):
    display_name: Optional[str] = None
    department: Optional[str] = None
    year: str
    bio: Optional[str] = None
    interests: List[str] = []
    image_url: Optional[str] = None
    vibe_photos: Optional[List[str]] = []
    prompts: Optional[List[dict]] = []


class ProfileRead(BaseModel):
    image_url: Optional[str] = None
    id: int
    user_id: int
    email: Optional[str] = None
    display_name: Optional[str]
    department: Optional[str]
    year: Optional[str]
    bio: Optional[str]
    interests: List[str] = []
    vibe_photos: Optional[List[str]] = []
    prompts: Optional[List[dict]] = []


class ImageUpdate(BaseModel):
    image_url: str

