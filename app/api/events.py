import logging
from datetime import datetime, timedelta, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import AuthenticatedUser, get_db
from app.core.redis import redis_service
from app.core.verified_dependencies import get_current_verified_user
from app.db.models import CampusEvent, EventRsvp, Notification, StudentProfile
from app.schemas.intercollege import (
    CampusEventCreate,
    CampusEventRead,
    EventRsvpRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["Campus Events"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _college_domain(user: AuthenticatedUser) -> str:
    if user.college_domain:
        return user.college_domain
    return user.email.rsplit("@", 1)[-1] if "@" in user.email else "unknown"


def _can_view_event(event: CampusEvent, user: AuthenticatedUser) -> bool:
    return (
        user.is_admin
        or event.scope == "global"
        or event.college_domain == _college_domain(user)
    )


async def _clear_events_cache() -> None:
    try:
        redis = redis_service.get_client()
        keys = [key async for key in redis.scan_iter(match="cache:events:*")]
        if keys:
            await redis.delete(*keys)
    except Exception:
        logger.exception("Could not clear the campus events cache")


@router.post("/", response_model=CampusEventRead)
async def create_event(
    event_in: CampusEventCreate,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_verified_user),
):
    if event_in.event_date <= _utcnow():
        raise HTTPException(status_code=400, detail="Event date must be in the future.")

    upcoming_count = db.query(CampusEvent).filter(
        CampusEvent.user_id == current_user.id,
        CampusEvent.event_date >= _utcnow(),
    ).count()
    if upcoming_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only have up to 5 upcoming events at a time.",
        )

    event = CampusEvent(
        user_id=current_user.id,
        title=event_in.title,
        description=event_in.description,
        event_date=event_in.event_date,
        venue=event_in.venue,
        category=event_in.category,
        scope=event_in.scope,
        college_domain=_college_domain(current_user),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    await _clear_events_cache()
    organizer_profile = db.query(StudentProfile).filter(
        StudentProfile.user_id == current_user.id
    ).first()

    return CampusEventRead(
        id=event.id,
        user_id=event.user_id,
        organizer_name=(
            organizer_profile.display_name
            if organizer_profile and organizer_profile.display_name
            else current_user.email.split("@")[0]
        ),
        organizer_email=current_user.email,
        organizer_department=organizer_profile.department if organizer_profile else None,
        organizer_year=organizer_profile.year if organizer_profile else None,
        title=event.title,
        description=event.description,
        event_date=event.event_date,
        venue=event.venue,
        category=event.category,
        scope=event.scope,
        college_domain=event.college_domain,
        created_at=event.created_at,
        rsvp_count=0,
        going_count=0,
        interested_count=0,
        has_rsvped=False,
        rsvp_status=None,
        is_mine=True,
    )


@router.get("/", response_model=List[CampusEventRead])
async def list_events(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    scope: Literal["college", "global"] = "college",
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_verified_user),
):
    current_domain = _college_domain(current_user)
    cutoff = _utcnow() - timedelta(hours=6)

    def fetch():
        query = db.query(CampusEvent).filter(CampusEvent.event_date >= cutoff)
        if scope == "college":
            if not current_user.is_admin:
                query = query.filter(CampusEvent.college_domain == current_domain)
        else:
            query = query.filter(CampusEvent.scope == "global")

        events = (
            query.order_by(CampusEvent.event_date.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        if not events:
            return []

        event_ids = [event.id for event in events]
        user_ids = {event.user_id for event in events}
        profiles = {
            profile.user_id: profile
            for profile in db.query(StudentProfile)
            .filter(StudentProfile.user_id.in_(user_ids))
            .all()
        }
        counts = {
            (event_id, rsvp_status): count
            for event_id, rsvp_status, count in db.query(
                EventRsvp.event_id,
                EventRsvp.status,
                func.count(EventRsvp.user_id),
            )
            .filter(EventRsvp.event_id.in_(event_ids))
            .group_by(EventRsvp.event_id, EventRsvp.status)
            .all()
        }
        user_rsvps = {
            rsvp.event_id: rsvp.status
            for rsvp in db.query(EventRsvp)
            .filter(
                EventRsvp.event_id.in_(event_ids),
                EventRsvp.user_id == current_user.id,
            )
            .all()
        }

        results = []
        for event in events:
            profile = profiles.get(event.user_id)
            going_count = counts.get((event.id, "going"), 0)
            interested_count = counts.get((event.id, "interested"), 0)
            rsvp_status = user_rsvps.get(event.id)
            results.append(
                CampusEventRead(
                    id=event.id,
                    user_id=event.user_id,
                    organizer_name=(
                        profile.display_name
                        if profile and profile.display_name
                        else event.user.email.split("@")[0]
                    ),
                    organizer_email=event.user.email if event.user else None,
                    organizer_department=profile.department if profile else None,
                    organizer_year=profile.year if profile else None,
                    title=event.title,
                    description=event.description,
                    event_date=event.event_date,
                    venue=event.venue,
                    category=event.category,
                    scope=event.scope,
                    college_domain=event.college_domain,
                    created_at=event.created_at,
                    rsvp_count=going_count + interested_count,
                    going_count=going_count,
                    interested_count=interested_count,
                    has_rsvped=rsvp_status is not None,
                    rsvp_status=rsvp_status,
                    is_mine=event.user_id == current_user.id or current_user.is_admin,
                )
            )
        return results

    return await run_in_threadpool(fetch)


@router.post("/{event_id}/rsvp")
async def toggle_event_rsvp(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_verified_user),
    rsvp_in: EventRsvpRequest | None = None,
):
    event = db.query(CampusEvent).filter(CampusEvent.id == event_id).first()
    if not event or not _can_view_event(event, current_user):
        raise HTTPException(status_code=404, detail="Event not found")

    selected_status = rsvp_in.status if rsvp_in else "going"
    existing = db.query(EventRsvp).filter(
        EventRsvp.user_id == current_user.id,
        EventRsvp.event_id == event_id,
    ).first()

    if existing and existing.status == selected_status:
        db.delete(existing)
        rsvp_status = None
        rsvped = False
    else:
        is_new_rsvp = existing is None
        if existing:
            existing.status = selected_status
        else:
            db.add(
                EventRsvp(
                    user_id=current_user.id,
                    event_id=event_id,
                    status=selected_status,
                )
            )
        rsvp_status = selected_status
        rsvped = True

        if is_new_rsvp and event.user_id != current_user.id:
            user_profile = db.query(StudentProfile).filter(
                StudentProfile.user_id == current_user.id
            ).first()
            name = user_profile.display_name if user_profile else "A student"
            db.add(
                Notification(
                    user_id=event.user_id,
                    message=f"{name} is {selected_status} for your event: '{event.title}'",
                    link="/feed",
                )
            )

    db.commit()
    status_counts = dict(
        db.query(EventRsvp.status, func.count(EventRsvp.user_id))
        .filter(EventRsvp.event_id == event_id)
        .group_by(EventRsvp.status)
        .all()
    )
    going_count = status_counts.get("going", 0)
    interested_count = status_counts.get("interested", 0)
    await _clear_events_cache()

    return {
        "rsvped": rsvped,
        "status": rsvp_status,
        "rsvp_count": going_count + interested_count,
        "going_count": going_count,
        "interested_count": interested_count,
    }


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_verified_user),
):
    event = db.query(CampusEvent).filter(CampusEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to delete this event.",
        )

    db.delete(event)
    db.commit()
    await _clear_events_cache()
