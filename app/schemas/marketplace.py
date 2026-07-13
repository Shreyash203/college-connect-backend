from pydantic import BaseModel
from typing import Optional

class MarketplaceItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    image_url: str
