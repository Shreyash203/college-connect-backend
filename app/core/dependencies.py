from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    email: str
    college_domain: str | None
    is_verified: bool
    is_admin: bool


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def decode_access_token(token: str) -> AuthenticatedUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = int(payload["sub"])
        email = payload["email"]
        college_domain = payload["college_domain"]
        is_verified = payload["is_verified"]
        is_admin = payload["is_admin"]
        if (
            payload.get("type") != "access"
            or not isinstance(email, str)
            or (college_domain is not None and not isinstance(college_domain, str))
            or not isinstance(is_verified, bool)
            or not isinstance(is_admin, bool)
        ):
            raise credentials_exception
    except (JWTError, KeyError, TypeError, ValueError):
        raise credentials_exception
    return AuthenticatedUser(
        id=user_id,
        email=email,
        college_domain=college_domain,
        is_verified=is_verified,
        is_admin=is_admin,
    )


def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:
    return decode_access_token(token)
