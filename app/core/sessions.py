"""Database-backed sessions shared across workers and application replicas."""
import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import HTTPException
from jose import JWTError, jwt

from app.core.config import settings
from app.core import security
from app.db.models import AuthSession, User


def token_digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def issue_session(db, user):
    session_id = str(uuid.uuid4())
    refresh_token = security.create_refresh_token(str(user.id), session_id=session_id)
    db.add(AuthSession(
        id=session_id,
        user_id=user.id,
        refresh_digest=token_digest(refresh_token),
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return session_id, refresh_token


def decode_refresh_token(token):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get('type') != 'refresh' or not isinstance(payload.get('sid'), str) or not payload['sid']:
            raise ValueError('Missing session')
        if not isinstance(payload.get('jti'), str) or not payload['jti']:
            raise ValueError('Missing token identifier')
        int(payload['sub'])
        return payload
    except (JWTError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail='Invalid or expired refresh token')


def validate_access_session(db, authenticated_user):
    if not authenticated_user.session_id:
        raise HTTPException(status_code=401, detail='Please sign in again')
    row = db.query(AuthSession).filter(
        AuthSession.id == authenticated_user.session_id,
        AuthSession.user_id == authenticated_user.id,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > datetime.utcnow(),
    ).first()
    user = db.query(User).filter(User.id == authenticated_user.id).first() if row else None
    if not row or not user or not user.is_verified:
        raise HTTPException(status_code=401, detail='Session expired or revoked')
    return user


def revoke_session(db, session_id, user_id):
    db.query(AuthSession).filter(
        AuthSession.id == session_id,
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ).update({'revoked_at': datetime.utcnow()}, synchronize_session=False)


def revoke_user_sessions(db, user_id):
    db.query(AuthSession).filter(
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ).update({'revoked_at': datetime.utcnow()}, synchronize_session=False)
