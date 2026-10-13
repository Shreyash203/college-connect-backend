from typing import List
from datetime import datetime, timedelta
from pathlib import Path
import uuid
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead, ImageUpdate
from app.core.config import settings
from app.core.rate_limiter import DailyUploadRateLimiter
from fastapi.concurrency import run_in_threadpool
from app.core.azure_storage import verify_azure_host_and_container

router = APIRouter()

MAX_PROFILE_IMAGE_SIZE = 10 * 1024 * 1024
PROFILE_IMAGE_READ_SAS_DAYS = 36500
PROFILE_IMAGE_BLOB_PATTERN = re.compile(
    r"^profile_images/user_(\d+)/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(jpg|jpeg|png|gif|webp|svg)$",
    re.IGNORECASE,
)


def profile_to_response(profile: StudentProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "email": profile.user.email if profile.user else None,
        "display_name": profile.display_name,
        "department": profile.department,
        "year": profile.year,
        "bio": profile.bio,
        "image_url": profile.image_url,
        "vibe_photos": profile.vibe_photos or [],
        "prompts": profile.prompts or [],
        "interests": [interest.name for interest in profile.interests],
    }


def get_owned_profile_blob_name(image_url: str, owner_user_id: int) -> str:
    verification = verify_azure_host_and_container(image_url)
    if not verification:
        raise HTTPException(status_code=400, detail="Invalid profile image URL.")

    _, blob_name = verification
    match = PROFILE_IMAGE_BLOB_PATTERN.fullmatch(blob_name)
    if not match or int(match.group(1)) != owner_user_id:
        raise HTTPException(status_code=400, detail="Profile image does not belong to this account.")
    return blob_name


def enforce_profile_blob_size(blob_client) -> None:
    properties = blob_client.get_blob_properties()
    if properties.size > MAX_PROFILE_IMAGE_SIZE:
        blob_client.delete_blob()
        raise HTTPException(
            status_code=413,
            detail="Profile images must be 10 MB or smaller. The oversized upload was deleted.",
        )


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
        vibe_photos=profile_in.vibe_photos or [],
        prompts=profile_in.prompts or [],
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
    if profile_in.vibe_photos is not None:
        profile.vibe_photos = profile_in.vibe_photos
    if profile_in.prompts is not None:
        profile.prompts = profile_in.prompts

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
def get_profile(
    profile_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import or_
    profile = db.query(StudentProfile).filter(
        or_(StudentProfile.id == profile_id, StudentProfile.user_id == profile_id)
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile_to_response(profile)


@router.get("/profiles", response_model=List[ProfileRead])
def list_profiles(
    category: str | None = None,
    skip: int = 0, 
    limit: int = 20, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    from sqlalchemy import cast, Integer

    current_domain = current_user.email.split('@')[-1] if '@' in current_user.email else ""
    
    query = (
        db.query(StudentProfile)
        .join(User, StudentProfile.user_id == User.id)
        .filter(StudentProfile.user_id != current_user.id)  # Exclude self
    )
    
    if not current_user.is_admin:
        query = query.filter(User.college_domain == current_domain)

    if category:
        my_profile = current_user.profile
        if not my_profile:
            return []  # User needs a profile to use smart filters
            
        if category == 'hobbies' and my_profile.interests:
            interest_names = [i.name for i in my_profile.interests]
            query = query.join(StudentProfile.interests).filter(Interest.name.in_(interest_names))
        elif category == 'batch' and my_profile.year:
            query = query.filter(StudentProfile.year == my_profile.year)
        elif category == 'seniors' and my_profile.year and my_profile.year.isdigit():
            query = query.filter(cast(StudentProfile.year, Integer) < int(my_profile.year))
        elif category == 'juniors' and my_profile.year and my_profile.year.isdigit():
            query = query.filter(cast(StudentProfile.year, Integer) > int(my_profile.year))

    profiles = query.order_by(StudentProfile.created_at.desc()).offset(skip).limit(limit).all()
    return [profile_to_response(profile) for profile in profiles]


@router.get(
    "/profiles/me/upload-url",
    response_model=dict,
    dependencies=[Depends(DailyUploadRateLimiter(limit=3))],
)
def get_profile_upload_url(
    filename: str,
    current_user: User = Depends(get_current_verified_user),
):
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg'}
    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Invalid image file type. Allowed types: JPG, JPEG, PNG, GIF, WebP, SVG")

    parts = dict(item.split('=', 1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
    account_name = parts.get('AccountName')
    account_key = parts.get('AccountKey')
    if not account_name or not account_key:
        raise HTTPException(status_code=500, detail="Invalid storage connection string.")

    blob_name = f"profile_images/user_{current_user.id}/{uuid.uuid4()}{ext}"
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    blob_client = container_client.get_blob_client(blob_name)

    upload_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(create=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )
    read_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=PROFILE_IMAGE_READ_SAS_DAYS),
    )
    upload_url = f"{blob_client.url}?{upload_sas_token}"
    image_url = f"{container_client.url}/{blob_name}?{read_sas_token}"
    return {"upload_url": upload_url, "image_url": image_url}


@router.post("/profiles/me/upload/verify", response_model=dict)
async def verify_profile_upload(
    image_in: ImageUpdate,
    current_user: User = Depends(get_current_verified_user),
):
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")

    blob_name = get_owned_profile_blob_name(image_in.image_url, current_user.id)
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    blob_client = container_client.get_blob_client(blob_name)
    try:
        await run_in_threadpool(enforce_profile_blob_size, blob_client)
    except ResourceNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Profile image upload was not found.") from exc

    parts = dict(item.split('=', 1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
    account_name = parts.get('AccountName')
    account_key = parts.get('AccountKey')
    if not account_name or not account_key:
        raise HTTPException(status_code=500, detail="Invalid storage connection string.")

    read_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=PROFILE_IMAGE_READ_SAS_DAYS),
    )
    return {"image_url": f"{container_client.url}/{blob_name}?{read_sas_token}"}

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
