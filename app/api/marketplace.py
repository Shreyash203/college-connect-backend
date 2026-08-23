from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import MarketplaceItem, User, MarketplaceInterest
from app.core.config import settings
from app.core.rate_limiter import DailyUploadRateLimiter
from fastapi.concurrency import run_in_threadpool
from app.core.redis import redis_service
import json
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from app.schemas.marketplace import MarketplaceItemCreate

router = APIRouter()

@router.get("/marketplace/items/upload-url", response_model=dict, dependencies=[Depends(DailyUploadRateLimiter(limit=20))])
def get_marketplace_upload_url(
    filename: str,
    current_user: User = Depends(get_current_verified_user),
):
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
    # We assume the container already exists and has the correct access policy.
    # Calling create_container() on every upload causes severe latency and potential timeouts.

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
    
    # Generate read-only SAS token for viewing (30 days) to bypass any strict Azure public access blocks
    read_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=36500), # 100 years to prevent expiration
    )
    image_url = f"{container_client.url}/{blob_name}?{read_sas_token}"
    
    return {"upload_url": upload_url, "image_url": image_url}

@router.post("/marketplace/items", response_model=dict)
async def create_marketplace_item(
    item_in: MarketplaceItemCreate,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    # Enforce maximum of 3 active listings per user
    active_count = db.query(MarketplaceItem).filter(MarketplaceItem.user_id == current_user.id).count()
    if active_count >= 3:
        raise HTTPException(
            status_code=400, 
            detail="You can only have 3 active items on the marketplace at a time. Please delete an old item to post a new one."
        )

    item = MarketplaceItem(
        user_id=current_user.id,
        title=item_in.title,
        description=item_in.description,
        image_url=item_in.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    
    redis = redis_service.get_client()
    try:
        keys = await redis.keys("cache:marketplace:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
    
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "image_url": item.image_url,
        "user_id": item.user_id,
        "is_mine": True
    }

@router.get("/marketplace/items", response_model=List[dict])
async def list_marketplace_items(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    # Auto-expiry: 14 days cutoff
    cutoff = datetime.utcnow() - timedelta(days=14)
    
    def fetch_items():
        # Extract exact literal domain (e.g., alumni.iith.ac.in or iith.ac.in)
        current_domain = current_user.email.split('@')[-1] if '@' in current_user.email else ""
        
        items = (
            db.query(MarketplaceItem)
            .join(User, MarketplaceItem.user_id == User.id)
            .filter(MarketplaceItem.created_at >= cutoff)
            .filter(User.college_domain == current_domain)
            .order_by(MarketplaceItem.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        if not items:
            return []
            
        item_ids = [i.id for i in items]
        interests = db.query(MarketplaceInterest).filter(MarketplaceInterest.item_id.in_(item_ids)).all()
        
        interest_map = {iid: [] for iid in item_ids}
        for interest in interests:
            interest_map[interest.item_id].append(interest.user_id)
            
        return [(i, interest_map[i.id]) for i in items]
        
    data = await run_in_threadpool(fetch_items)
    
    results = []
    for i, interested_users in data:
        results.append({
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "image_url": i.image_url,
            "user_id": i.user_id,
            "email": i.user.email if i.user else None,
            "is_mine": (i.user_id == current_user.id) or current_user.is_admin,
            "interest_count": len(interested_users),
            "has_indicated_interest": current_user.id in interested_users
        })
        
    return results

@router.post("/marketplace/items/{item_id}/interest")
async def toggle_interest(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    item = db.query(MarketplaceItem).filter(MarketplaceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    existing = db.query(MarketplaceInterest).filter(
        MarketplaceInterest.item_id == item_id,
        MarketplaceInterest.user_id == current_user.id
    ).first()
    
    if existing:
        db.delete(existing)
        interested = False
    else:
        new_interest = MarketplaceInterest(user_id=current_user.id, item_id=item_id)
        db.add(new_interest)
        interested = True
        
    db.commit()
    
    interest_count = db.query(MarketplaceInterest).filter(MarketplaceInterest.item_id == item_id).count()
    return {"interested": interested, "interest_count": interest_count}

@router.delete("/marketplace/items/{item_id}", status_code=204)
async def delete_marketplace_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    item = db.query(MarketplaceItem).filter(MarketplaceItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Marketplace item not found")
    if item.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this item")
    
    db.delete(item)
    db.commit()
    
    redis = redis_service.get_client()
    try:
        keys = await redis.keys("cache:marketplace:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
    
    return
