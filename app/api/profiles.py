from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import StudentProfile, Interest, User
from app.schemas.profiles import ProfileCreate, ProfileRead

router = APIRouter()


def profile_to_response(profile: StudentProfile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "department": profile.department,
        "year": profile.year,
        "bio": profile.bio,
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
