from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead, ImageUpdate
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


from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead, ImageUpdate
from app.core.config import settings

router = APIRouter()

from fastapi import UploadFile, File
import uuid
from pathlib import Path
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta


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


@router.get("/profiles/me/upload-url", response_model=dict)
def get_profile_upload_url(
    filename: str,
    current_user: User = Depends(get_current_verified_user),
):
    if not settings.AZURE_STORAGE_CONNECTION_STRING or not getattr(settings, "AZURE_STORAGE_CONTAINER_NAME", None):
        raise HTTPException(status_code=500, detail="Azure storage configuration missing.")
    
    parts = dict(item.split('=', 1) for item in settings.AZURE_STORAGE_CONNECTION_STRING.split(';') if item)
    account_name = parts.get('AccountName')
    account_key = parts.get('AccountKey')
    if not account_name or not account_key:
        raise HTTPException(status_code=500, detail="Invalid storage connection string.")

    ext = Path(filename).suffix
    blob_name = f"profile_images/{uuid.uuid4()}{ext}"
    
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

    # Generate upload SAS token with WRITE and CREATE permissions
    upload_sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=settings.AZURE_STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(write=True, create=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )
    upload_url = f"{container_client.url}/{blob_name}?{upload_sas_token}"
    
    # Generate read-only SAS token for viewing
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
