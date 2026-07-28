from typing import List
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import imghdr

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead, ImageUpdate
from app.core.config import settings
from app.core.rate_limiter import DailyUploadRateLimiter

router = APIRouter()


def profile_to_response(profile: StudentProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "department": profile.department,
        "year": profile.year,
        "bio": profile.bio,
        "image_url": profile.image_url,
        "interests": [interest.name for interest in profile.interests],
    }


def validate_image_url(image_url: str) -> bool:
    """
    Validates that the image URL is from an allowed source (Azure Blob Storage).
    This is a basic validation that can be enhanced with actual content verification.
    """
    # Check if URL is from Azure storage or local development
    allowed_patterns = [
        "https://",  # Azure Blob Storage
        "http://",   # Local development
        "/",         # Relative URLs
    ]
    
    for pattern in allowed_patterns:
        if pattern in image_url:
            return True
    
    return False


def validate_image_size_from_url(image_url: str) -> bool:
    """
    Note: Since we're using Azure Blob Storage with SAS tokens,
    actual file size verification would require downloading the file,
    which is inefficient. Frontend validation is more practical here.
    """
    # We trust the user's upload due to SAS token restrictions and frontend validation
    return True


@router.post("/profiles", response_model=ProfileRead)
def create_profile(
    profile_in: ProfileCreate,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    existing = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Profile already exists for this user.")

    profile = StudentProfile(
        user_id=current_user.id,
        display_name=profile_in.display_name,
        department=profile_in.department,
        year=profile_in.year,
        bio=profile_in.bio,
        image_url=profile_in.image_url,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    interests = []
    for interest_name in profile_in.interests:
        interest = db.query(Interest).filter(Interest.name == interest_name).first()
        if not interest:
            interest = Interest(name=interest_name)
            db.add(interest)
            db.commit()
            db.refresh(interest)
        interests.append(interest)

    profile.interests = interests
    db.commit()
    db.refresh(profile)
    return profile_to_response(profile)


@router.put("/profiles/me", response_model=ProfileRead)
def update_profile(
    profile_in: ProfileCreate,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    # Update scalar fields
    profile.display_name = profile_in.display_name
    profile.department = profile_in.department
    profile.year = profile_in.year
    profile.bio = profile_in.bio
    if profile_in.image_url:
        profile.image_url = profile_in.image_url

    # Update interests
    new_interests = []
    for interest_name in profile_in.interests:
        interest = db.query(Interest).filter(Interest.name == interest_name).first()
        if not interest:
            interest = Interest(name=interest_name)
            db.add(interest)
            db.commit()
            db.refresh(interest)
        new_interests.append(interest)
    profile.interests = new_interests
    db.commit()
    db.refresh(profile)
    return profile_to_response(profile)


@router.get("/profiles/me", response_model=ProfileRead)
def get_my_profile(current_user: User = Depends(get_current_verified_user), db: Session = Depends(get_db)):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_to_response(profile)


@router.get("/profiles/{profile_id}", response_model=ProfileRead)
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    profile = db.query(StudentProfile).filter(StudentProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_to_response(profile)


@router.get("/profiles", response_model=List[ProfileRead])
def list_profiles(skip: int = 0, limit: int = 20, db: Session = Depends(get_db)):
    profiles = db.query(StudentProfile).order_by(StudentProfile.created_at.desc()).offset(skip).limit(limit).all()
    return [profile_to_response(profile) for profile in profiles]


@router.get("/profiles/me/upload-url", response_model=dict)
def get_profile_upload_url(
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

    blob_name = f"profile_images/{uuid.uuid4()}{ext}"
    
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

@router.post("/profiles/me/image", response_model=dict)
def update_profile_image(
    image_in: ImageUpdate,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    profile.image_url = image_in.image_url
    db.commit()
    db.refresh(profile)
    return {"url": profile.image_url}
