from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.rate_limiter import SlidingWindowRateLimiter

from app.core.dependencies import get_db
from app.db.models import User, StudentApp
from app.schemas.intercollege import StudentAppCreate, StudentAppRead
from app.core.verified_dependencies import get_current_verified_user

router = APIRouter(prefix="/launchpad", tags=["Launchpad"])

@router.post("/", response_model=StudentAppRead, dependencies=[Depends(SlidingWindowRateLimiter(limit=2, window_seconds=3600))])
def create_app(
    app_in: StudentAppCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    college_domain = current_user.email.split("@")[-1] if "@" in current_user.email else "unknown"
    
    new_app = StudentApp(
        user_id=current_user.id,
        college_domain=college_domain,
        app_name=app_in.app_name,
        description=app_in.description,
        app_url=app_in.app_url
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    
    return new_app

@router.get("/", response_model=List[StudentAppRead])
def get_all_apps(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    # Fetch all student apps globally (inter-college)
    return db.query(StudentApp).order_by(StudentApp.created_at.desc()).offset(skip).limit(limit).all()

@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_app(
    app_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    student_app = db.query(StudentApp).filter(StudentApp.id == app_id).first()
    if not student_app:
        raise HTTPException(status_code=404, detail="App not found")
        
    if student_app.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this app")
        
    db.delete(student_app)
    db.commit()
