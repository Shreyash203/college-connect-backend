import random
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt

from app.core.config import settings


def create_email_verification_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "type": "email_verification",
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_email_verification_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired verification token.") from exc

    if payload.get("type") != "email_verification":
        raise ValueError("Invalid verification token type.")

    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Invalid verification token payload.")

    return int(user_id)


def generate_otp_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def is_verification_otp_valid(user, otp: str) -> bool:
    if not user.verification_otp or not user.verification_otp_expires_at:
        return False
    if user.verification_otp != otp:
        return False
    return datetime.utcnow() <= user.verification_otp_expires_at
