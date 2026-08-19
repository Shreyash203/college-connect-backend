from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.rate_limiter import SlidingWindowRateLimiter
from fastapi.concurrency import run_in_threadpool
from app.core.redis import redis_service
import json

from app.core.dependencies import get_db
from app.db.models import User, Confession, ConfessionLike
from app.schemas.intercollege import ConfessionCreate, ConfessionRead
from app.core.verified_dependencies import get_current_verified_user

from datetime import datetime, timedelta

router = APIRouter(prefix="/confessions", tags=["Confessions"])

@router.post("/", response_model=ConfessionRead)
async def create_confession(
    confession_in: ConfessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    # User-based rate limiter: max 3 confessions per hour
    cutoff = datetime.utcnow() - timedelta(hours=1)
    recent_confessions = db.query(Confession).filter(
        Confession.user_id == current_user.id,
        Confession.created_at >= cutoff
    ).count()
    
    if recent_confessions >= 3:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You can only post 3 confessions per hour to prevent spam."
        )

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
        keys = await redis.keys("cache:confessions:global:*")
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
    cache_key = f"cache:confessions:global:{skip}:{limit}"
    redis = redis_service.get_client()
    
    data = None
    try:
        cached_data = await redis.get(cache_key)
        if cached_data:
            data = json.loads(cached_data)
    except Exception:
        pass

    if data is None:
        # Cache Miss - Auto-expiry: 48 hours cutoff
        cutoff = datetime.utcnow() - timedelta(hours=48)
        
        def fetch_confessions_from_db():
            confessions = (
                db.query(Confession)
                .filter(Confession.created_at >= cutoff)
                .order_by(Confession.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
            if not confessions:
                return []
                
            confession_ids = [c.id for c in confessions]
            likes = db.query(ConfessionLike).filter(ConfessionLike.confession_id.in_(confession_ids)).all()
            
            likes_map = {cid: [] for cid in confession_ids}
            for like in likes:
                likes_map[like.confession_id].append(like.user_id)
                
            serialized_data = []
            for c in confessions:
                serialized_data.append({
                    "id": c.id,
                    "user_id": c.user_id,
                    "college_domain": c.college_domain,
                    "content": c.content,
                    "created_at": c.created_at.isoformat(),
                    "liked_by_users": likes_map[c.id]
                })
            return serialized_data
            
        data = await run_in_threadpool(fetch_confessions_from_db)
        
        try:
            if data:
                await redis.setex(cache_key, 60, json.dumps(data))
        except Exception:
            pass
    
    results = []
    for item in data:
        results.append(ConfessionRead(
            id=item["id"],
            college_domain=item["college_domain"],
            content=item["content"],
            created_at=item["created_at"],
            is_mine=(item["user_id"] == current_user.id) or current_user.is_admin,
            likes_count=len(item["liked_by_users"]),
            has_liked=current_user.id in item["liked_by_users"]
        ))
        
    return results

@router.post("/{confession_id}/like")
async def toggle_like(
    confession_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_verified_user)
):
    confession = db.query(Confession).filter(Confession.id == confession_id).first()
    if not confession:
        raise HTTPException(status_code=404, detail="Confession not found")
        
    existing_like = db.query(ConfessionLike).filter(
        ConfessionLike.confession_id == confession_id,
        ConfessionLike.user_id == current_user.id
    ).first()
    
    if existing_like:
        db.delete(existing_like)
        liked = False
    else:
        new_like = ConfessionLike(user_id=current_user.id, confession_id=confession_id)
        db.add(new_like)
        liked = True
        
    db.commit()
    
    likes_count = db.query(ConfessionLike).filter(ConfessionLike.confession_id == confession_id).count()
    return {"liked": liked, "likes_count": likes_count}

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
        keys = await redis.keys("cache:confessions:global:*")
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass
