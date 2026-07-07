from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead
from app.core.config import settings

router = APIRouter()

from fastapi import UploadFile, File
import uuid
from pathlib import Path
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions


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
def list_profiles(db: Session = Depends(get_db)):
    profiles = db.query(StudentProfile).all()
    return [profile_to_response(profile) for profile in profiles]


@router.post("/profiles/me/image", response_model=dict)
def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    # Initialize Azure Blob client
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")
    blob_service = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container_client = blob_service.get_container_client(settings.AZURE_STORAGE_CONTAINER_NAME)
    # Ensure container exists and is publicly readable
    try:
        container_client.create_container()
        # Set public access so blobs can be accessed directly via URL
        container_client.set_container_access_policy(public_access='blob')
    except Exception:
        # Container may already exist; attempt to set public access anyway
        try:
            container_client.set_container_access_policy(public_access='blob')
        except Exception:
            pass
    # Generate unique blob name
    ext = Path(file.filename).suffix
    blob_name = f"profile_images/{uuid.uuid4()}{ext}"
    # Upload
    container_client.upload_blob(blob_name, file.file, overwrite=True)
    # Generate a SAS token for the blob (private storage)
    from datetime import datetime, timedelta
    from azure.storage.blob import generate_blob_sas, BlobSasPermissions
    # Extract account name and key from connection string
    parts = dict(item.split('=',1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
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
    url = f"{container_client.url}/{blob_name}?{sas_token}"
    # Log the signed URL for debugging
    print(f"[DEBUG] Uploaded image SAS URL: {url}")
    # Update profile record
    profile = db.query(StudentProfile).filter(StudentProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
    profile.image_url = url
    db.commit()
    db.refresh(profile)
    return {"url": url}

    profiles = db.query(StudentProfile).all()
    return [profile_to_response(profile) for profile in profiles]
