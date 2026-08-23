from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.rate_limiter import SlidingWindowRateLimiter
from fastapi.concurrency import run_in_threadpool
from app.core.redis import redis_service
import json

from app.core.dependencies import get_db
from app.db.models import User, StudentApp
from app.schemas.intercollege import StudentAppCreate, StudentAppRead
from app.core.verified_dependencies import get_current_verified_user

from datetime import datetime, timedelta

router = APIRouter(prefix="/launchpad", tags=["Launchpad"])

@router.post("/", response_model=StudentAppRead)
def create_app(
    app_in: StudentAppCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    existing_app = db.query(StudentApp).filter(StudentApp.user_id == current_user.id).first()
    if existing_app:
        raise HTTPException(
            status_code=400,
            detail="You can only have 1 active project on Launchpad at a time. Please delete your existing project before launching a new one."
        )

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
    
    return StudentAppRead(
        id=new_app.id,
        app_name=new_app.app_name,
        description=new_app.description,
        app_url=new_app.app_url,
        college_domain=new_app.college_domain,
        created_at=new_app.created_at,
        user_id=new_app.user_id,
        email=current_user.email,
        is_mine=True
    )

@router.get("/", response_model=List[StudentAppRead])
async def get_all_apps(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    cache_key = f"cache:launchpad:{skip}:{limit}"
    redis = redis_service.get_client()
    
    try:
        cached_data = await redis.get(cache_key)
        if cached_data:
            apps = json.loads(cached_data)
            for app in apps:
                app["is_mine"] = (app["user_id"] == current_user.id) or current_user.is_admin
            return apps
    except Exception:
        pass

    # Auto-expiry: 14 days cutoff
    cutoff = datetime.utcnow() - timedelta(days=14)
    
    def fetch_apps():
        return (
            db.query(StudentApp)
            .filter(StudentApp.created_at >= cutoff)
            .order_by(StudentApp.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        
    apps = await run_in_threadpool(fetch_apps)
    
    results = []
    cache_payload = []
    for a in apps:
        cache_payload.append({
            "id": a.id,
            "user_id": a.user_id,
            "app_name": a.app_name,
            "description": a.description,
            "app_url": a.app_url,
            "college_domain": a.college_domain,
            "email": a.user.email if a.user else None,
            "created_at": a.created_at.isoformat() + "Z"
        })
        
        results.append(StudentAppRead(
            id=a.id,
            app_name=a.app_name,
            description=a.description,
            app_url=a.app_url,
            college_domain=a.college_domain,
            created_at=a.created_at,
            user_id=a.user_id,
            email=a.user.email if a.user else None,
            is_mine=(a.user_id == current_user.id) or current_user.is_admin
        ))
        
    try:
        await redis.setex(cache_key, 30, json.dumps(cache_payload))
    except Exception:
        pass
        
    return results

@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_app(
    app_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    student_app = db.query(StudentApp).filter(StudentApp.id == app_id).first()
    if not student_app:
        raise HTTPException(status_code=404, detail="App not found")
        
    if student_app.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this app")
        
    db.delete(student_app)
    db.commit()
