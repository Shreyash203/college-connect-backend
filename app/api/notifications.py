from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.db.models import User, Notification
from app.schemas.notifications import NotificationRead
from app.core.verified_dependencies import get_current_verified_user

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)

@router.get("/", response_model=List[NotificationRead])
def get_notifications(
    skip: int = 0,
    limit: int = 20,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
):
    notifications = db.query(Notification).filter(Notification.user_id == current_user.id).order_by(Notification.created_at.desc()).offset(skip).limit(limit).all()
    return notifications

@router.put("/{notification_id}/read")
def mark_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db)
):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()
    
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    notification.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}
