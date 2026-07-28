from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.rate_limiter import SlidingWindowRateLimiter

from app.core.dependencies import get_db
from app.db.models import User, Confession
from app.schemas.intercollege import ConfessionCreate, ConfessionRead
from app.core.verified_dependencies import get_current_verified_user

from datetime import datetime, timedelta

router = APIRouter(prefix="/confessions", tags=["Confessions"])

@router.post("/", response_model=ConfessionRead, dependencies=[Depends(SlidingWindowRateLimiter(limit=5, window_seconds=3600))])
def create_confession(
    confession_in: ConfessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    college_domain = current_user.email.split("@")[-1] if "@" in current_user.email else "unknown"
    
    new_confession = Confession(
        user_id=current_user.id,
        college_domain=college_domain,
        content=confession_in.content
    )
    db.add(new_confession)
    db.commit()
    db.refresh(new_confession)
    
    return ConfessionRead(
        id=new_confession.id,
        college_domain=new_confession.college_domain,
        content=new_confession.content,
        created_at=new_confession.created_at,
        is_mine=True
    )

@router.get("/", response_model=List[ConfessionRead])
def get_all_confessions(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    # Auto-expiry: 48 hours cutoff
    cutoff = datetime.utcnow() - timedelta(hours=48)
    confessions = (
        db.query(Confession)
        .filter(Confession.created_at >= cutoff)
        .order_by(Confession.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    results = []
    for c in confessions:
        results.append(ConfessionRead(
            id=c.id,
            college_domain=c.college_domain,
            content=c.content,
            created_at=c.created_at,
            is_mine=(c.user_id == current_user.id)
        ))
    return results

@router.delete("/{confession_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_confession(
    confession_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    confession = db.query(Confession).filter(Confession.id == confession_id).first()
    if not confession:
        raise HTTPException(status_code=404, detail="Confession not found")
        
    if confession.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this confession")
        
    db.delete(confession)
    db.commit()
