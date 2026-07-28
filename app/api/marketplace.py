from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import MarketplaceItem, User
from app.core.config import settings
from app.core.rate_limiter import DailyUploadRateLimiter
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from app.schemas.marketplace import MarketplaceItemCreate

router = APIRouter()

@router.get("/marketplace/items/upload-url", response_model=dict)
def get_marketplace_upload_url(
    filename: str,
    current_user: User = Depends(get_current_verified_user),
):
    # Apply rate limiting (3 uploads per day)
    daily_limiter = DailyUploadRateLimiter(limit=3)
    
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")
    
    # Validate filename extension
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid image file type. Allowed types: JPG, JPEG, PNG, GIF, WebP, SVG")

    parts = dict(item.split('=', 1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
    account_name = parts.get('AccountName')
    account_key = parts.get('AccountKey')
    if not account_name or not account_key:
        raise HTTPException(status_code=500, detail="Invalid storage connection string.")

    blob_name = f"marketplace_images/{uuid.uuid4()}{ext}"
    
    # Ensure container exists and is publicly accessible
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    try:
        container_client.create_container()
        container_client.set_container_access_policy(public_access='blob')
    except Exception:
        try:
            container_client.set_container_access_policy(public_access='blob')
        except Exception:
            pass

    # Generate upload SAS token with WRITE and CREATE permissions (1 hour expiry)
    upload_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )
    upload_url = f"{container_client.url}/{blob_name}?{upload_sas_token}"
    
    # Generate read-only SAS token for viewing (30 days)
    read_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=30),
    )
    image_url = f"{container_client.url}/{blob_name}?{read_sas_token}"
    
    return {"upload_url": upload_url, "image_url": image_url}

@router.post("/marketplace/items", response_model=dict)
def create_marketplace_item(
    item_in: MarketplaceItemCreate,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    item = MarketplaceItem(
        user_id=current_user.id,
        title=item_in.title,
        description=item_in.description,
        image_url=item_in.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "image_url": item.image_url,
        "user_id": item.user_id,
        "is_mine": True
    }

@router.get("/marketplace/items", response_model=List[dict])
def list_marketplace_items(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    # Auto-expiry: 14 days cutoff
    cutoff = datetime.utcnow() - timedelta(days=14)
    items = (
        db.query(MarketplaceItem)
        .filter(MarketplaceItem.created_at >= cutoff)
        .order_by(MarketplaceItem.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "image_url": i.image_url,
            "user_id": i.user_id,
            "is_mine": (i.user_id == current_user.id)
        }
        for i in items
    ]

@router.delete("/marketplace/items/{item_id}", status_code=204)
def delete_marketplace_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    item = db.query(MarketplaceItem).filter(MarketplaceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Marketplace item not found")
    if item.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this item")
    
    db.delete(item)
    db.commit()
    return
