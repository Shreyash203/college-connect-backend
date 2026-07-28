from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.rate_limiter import SlidingWindowRateLimiter
from fastapi.concurrency import run_in_threadpool
from app.core.redis import redis_service
import json

from app.core.dependencies import get_db
from app.db.models import User, Confession
from app.schemas.intercollege import ConfessionCreate, ConfessionRead
from app.core.verified_dependencies import get_current_verified_user

from datetime import datetime, timedelta

router = APIRouter(prefix="/confessions", tags=["Confessions"])

@router.post("/", response_model=ConfessionRead, dependencies=[Depends(SlidingWindowRateLimiter(limit=5, window_seconds=3600))])
async def create_confession(
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
    
    # Invalidate cache so the new post appears instantly
    redis = redis_service.get_client()
    try:
        keys = await redis.keys("cache:confessions:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
    
    return ConfessionRead(
        id=new_confession.id,
        college_domain=new_confession.college_domain,
        content=new_confession.content,
        created_at=new_confession.created_at,
        is_mine=True
    )

@router.get("/", response_model=List[ConfessionRead])
async def get_all_confessions(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    cache_key = f"cache:confessions:{skip}:{limit}"
    redis = redis_service.get_client()
    
    try:
        cached_data = await redis.get(cache_key)
        if cached_data:
            posts = json.loads(cached_data)
            for post in posts:
                post["is_mine"] = (post["user_id"] == current_user.id) or current_user.is_admin
            return posts
    except Exception:
        pass

    # Auto-expiry: 48 hours cutoff
    cutoff = datetime.utcnow() - timedelta(hours=48)
    
    def fetch_confessions():
        return (
            db.query(Confession)
            .filter(Confession.created_at >= cutoff)
            .order_by(Confession.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        
    confessions = await run_in_threadpool(fetch_confessions)
    
    results = []
    cache_payload = []
    for c in confessions:
        # For cache
        cache_payload.append({
            "id": c.id,
            "user_id": c.user_id,
            "college_domain": c.college_domain,
            "content": c.content,
            "created_at": c.created_at.isoformat()
        })
        
        # For actual response
        results.append(ConfessionRead(
            id=c.id,
            college_domain=c.college_domain,
            content=c.content,
            created_at=c.created_at,
            is_mine=(c.user_id == current_user.id) or current_user.is_admin
        ))
        
    try:
        await redis.setex(cache_key, 30, json.dumps(cache_payload))
    except Exception:
        pass
        
    return results

@router.delete("/{confession_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_confession(
    confession_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    confession = db.query(Confession).filter(Confession.id == confession_id).first()
    if not confession:
        raise HTTPException(status_code=404, detail="Confession not found")
        
    if confession.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this confession")
        
    db.delete(confession)
    db.commit()
    
    # Invalidate cache so the deleted post disappears instantly
    redis = redis_service.get_client()
    try:
        keys = await redis.keys("cache:confessions:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
