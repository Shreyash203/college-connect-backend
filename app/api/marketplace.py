from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import MarketplaceItem, User
from app.core.config import settings
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
from pathlib import Path
import uuid

router = APIRouter()

def _upload_blob(file: UploadFile) -> str:
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    try:
        container_client.create_container()
    except Exception:
        pass
    ext = Path(file.filename).suffix
    blob_name = f"marketplace_images/{uuid.uuid4()}{ext}"
    container_client.upload_blob(blob_name, file.file, overwrite=True)
    # SAS token for private storage
    parts = dict(item.split('=', 1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
    account_name = parts.get('AccountName')
    account_key = parts.get('AccountKey')
    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=30),
    )
    return f"{container_client.url}/{blob_name}?{sas_token}"

@router.post("/marketplace/items", response_model=dict)
def create_marketplace_item(
    title: str = Form(...),
    description: str = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    image_url = _upload_blob(file)
    item = MarketplaceItem(
        user_id=current_user.id,
        title=title,
        description=description,
        image_url=image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "image_url": item.image_url,
    }

@router.get("/marketplace/items", response_model=List[dict])
def list_marketplace_items(db: Session = Depends(get_db)):
    items = db.query(MarketplaceItem).order_by(MarketplaceItem.created_at.desc()).all()
    return [
        {
            "id": i.id,
            "title": i.title,
            "description": i.description,
            "image_url": i.image_url,
        }
        for i in items
    ]
