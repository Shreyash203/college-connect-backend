import uuid
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie, Body
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
from sqlalchemy.orm import Session
import redis.asyncio as aioredis

from app.core import email_client, email_verification, security
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User, StudentProfile, profile_interests, AuthorizedDomain
from app.core.redis import get_redis
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from app.core.rate_limiter import SlidingWindowRateLimiter, DailyUploadRateLimiter
from app.schemas.auth import (
    DeleteUserRequest,
    UserCreate,
    Token,
    RegisterResponse,
    VerifyRegistrationRequest,
    ResendOtpRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    GoogleLoginRequest,
)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _send_email_or_dev_fallback(to_address: str, subject: str, html_body: str, plain_body: str):
    email_service = email_client.EmailService()
    try:
        result = email_service.send_email(to_address=to_address, subject=subject, html_body=html_body, plain_body=plain_body)
        if isinstance(result, dict) and result.get("status") == "dev-fallback":
            return result
    except Exception as exc:
        if settings.ENV.lower() in {"development", "dev", "test"}:
            return {"status": "dev-fallback", "message": str(exc)}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send email."
        ) from exc
    return None


@router.post("/auth/register", response_model=RegisterResponse, dependencies=[Depends(SlidingWindowRateLimiter(limit=50, window_seconds=60))])
async def register(
    user_create: UserCreate, 
    db: Session = Depends(get_db), 
    redis_client: aioredis.Redis = Depends(get_redis)
):
    email_domain = user_create.email.split("@")[-1].lower()
    
    is_authorized = db.query(AuthorizedDomain).filter(AuthorizedDomain.domain == email_domain).first()
    if not is_authorized:
        if email_domain.endswith(('.ac.in', '.edu.in')):
            try:
                new_domain = AuthorizedDomain(domain=email_domain)
                db.add(new_domain)
                db.commit()
            except Exception:
                db.rollback() # Handle rare race conditions cleanly
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only authorized email domains are permitted.",
            )

    if len(user_create.password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be 72 bytes or fewer.",
        )

    existing = db.query(User).filter(User.email == user_create.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    # Generate secure, unique pending ID and OTP code
    pending_id = str(uuid.uuid4())
    otp_code = email_verification.generate_otp_code()

    try:
        password_hash = security.get_password_hash(user_create.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Delete any existing registration attempt for this email
    old_pending_id = await redis_client.get(f"pending_email:{user_create.email}")
    if old_pending_id:
        await redis_client.delete(f"pending_registration:{old_pending_id}")

    # Set registration data in Redis (10-minute expiration)
    pending_data = {
        "email": user_create.email,
        "password_hash": password_hash,
        "otp": otp_code,
    }
    await redis_client.setex(f"pending_registration:{pending_id}", 600, json.dumps(pending_data))
    await redis_client.setex(f"pending_email:{user_create.email}", 600, pending_id)

    subject = "Verify your College Connect email"
    html_body = (
        f"<p>Hi,</p>"
        f"<p>Your verification code is <strong>{otp_code}</strong>.</p>"
        f"<p>Enter this code in the app to verify your email.</p>"
        f"<p>If you did not sign up, ignore this message.</p>"
    )
    plain_body = (
        f"Hi,\n\n"
        f"Your verification code is {otp_code}.\n"
        f"Enter this code in the app to verify your email.\n\n"
        f"If you did not sign up, ignore this message."
    )

    _send_email_or_dev_fallback(to_address=user_create.email, subject=subject, html_body=html_body, plain_body=plain_body)

    return RegisterResponse(pending_id=pending_id, message="Registration initiated. Check your email for the verification code.")


@router.post("/auth/verify-registration", response_model=Token, dependencies=[Depends(SlidingWindowRateLimiter(limit=100, window_seconds=60))])
async def verify_registration(
    payload: VerifyRegistrationRequest, 
    response: Response,
    db: Session = Depends(get_db), 
    redis_client: aioredis.Redis = Depends(get_redis)
):
    pending_key = f"pending_registration:{payload.pending_id}"
    pending_data_str = await redis_client.get(pending_key)
    if not pending_data_str:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration request not found or expired.")

    pending_data = json.loads(pending_data_str)

    if pending_data["otp"] != payload.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code.")

    existing_user = db.query(User).filter(User.email == pending_data["email"]).first()
    if existing_user:
        await redis_client.delete(pending_key)
        await redis_client.delete(f"pending_email:{pending_data['email']}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    user = User(
        email=pending_data["email"],
        college_domain=pending_data["email"].split('@')[-1] if '@' in pending_data["email"] else "",
        password_hash=pending_data["password_hash"],
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Clean up Redis records
    await redis_client.delete(pending_key)
    await redis_client.delete(f"pending_email:{pending_data['email']}")

    access_token = security.create_access_token(subject=str(user.id))
    refresh_token = security.create_refresh_token(subject=str(user.id))
    
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "user_id": user.id
    }


@router.post("/auth/resend-otp", dependencies=[Depends(SlidingWindowRateLimiter(limit=30, window_seconds=60))])
async def resend_otp(
    payload: ResendOtpRequest, 
    redis_client: aioredis.Redis = Depends(get_redis)
):
    pending_key = f"pending_registration:{payload.pending_id}"
    pending_data_str = await redis_client.get(pending_key)
    if not pending_data_str:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration request not found or expired.")

    pending_data = json.loads(pending_data_str)
    new_otp = email_verification.generate_otp_code()
    pending_data["otp"] = new_otp

    # Store updated registration data and reset the TTL to 10 minutes
    await redis_client.setex(pending_key, 600, json.dumps(pending_data))
    await redis_client.expire(f"pending_email:{pending_data['email']}", 600)

    subject = "Verify your College Connect email"
    html_body = (
        f"<p>Hi,</p>"
        f"<p>Your new verification code is <strong>{new_otp}</strong>.</p>"
        f"<p>Enter this code in the app to verify your email.</p>"
        f"<p>If you did not sign up, ignore this message.</p>"
    )
    plain_body = (
        f"Hi,\n\n"
        f"Your new verification code is {new_otp}.\n"
        f"Enter this code in the app to verify your email.\n\n"
        f"If you did not sign up, ignore this message."
    )

    _send_email_or_dev_fallback(to_address=pending_data["email"], subject=subject, html_body=html_body, plain_body=plain_body)

    return {"message": "A new verification code has been sent to your email."}


@router.post("/auth/login", response_model=Token, dependencies=[Depends(SlidingWindowRateLimiter(limit=50, window_seconds=60))])
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address must be verified before login.",
        )
    access_token = security.create_access_token(subject=str(user.id), expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    refresh_token = security.create_refresh_token(subject=str(user.id))
    
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer"
    }


import requests as http_requests

@router.post("/auth/google", response_model=Token, dependencies=[Depends(SlidingWindowRateLimiter(limit=50, window_seconds=60))])
async def google_login(
    payload: GoogleLoginRequest, 
    response: Response,
    db: Session = Depends(get_db)
):
    id_info = None
    try:
        id_info = google_id_token.verify_oauth2_token(
            payload.credential, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )
    except Exception:
        try:
            resp = http_requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={payload.credential}", timeout=5)
            if resp.status_code == 200:
                id_info = resp.json()
            else:
                raise Exception(resp.text)
        except Exception as fallback_exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Google token: {str(fallback_exc)}"
            )

    email = id_info.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Google token missing email.")

    domain = email.split("@")[-1].lower() if "@" in email else ""
    
    is_authorized = db.query(AuthorizedDomain).filter(AuthorizedDomain.domain == domain).first()
    if not is_authorized:
        if domain.endswith(('.ac.in', '.edu.in')):
            try:
                new_domain = AuthorizedDomain(domain=domain)
                db.add(new_domain)
                db.commit()
            except Exception:
                db.rollback()
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your college domain (@{domain}) is not authorized for College Connect."
            )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            college_domain=domain,
            password_hash=security.get_password_hash(uuid.uuid4().hex),
            is_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_verified:
        user.is_verified = True
        db.commit()

    access_token = security.create_access_token(
        subject=str(user.id), 
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh_token = security.create_refresh_token(subject=str(user.id))
    
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    )
    
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "user_id": user.id
    }


@router.post("/auth/refresh")
async def refresh_token(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db)
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    try:
        payload = jwt.decode(refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub") 
        token_type: str = payload.get("type")
        if user_id is None or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
            
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.is_verified:
            raise HTTPException(status_code=401, detail="User not found or inactive")
            
        # Generate new tokens
        new_access_token = security.create_access_token(subject=str(user.id))
        new_refresh_token = security.create_refresh_token(subject=str(user.id))
        
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=True,
            samesite="none",
            max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token", samesite="none", secure=True)
    return {"message": "Logged out successfully"}


@router.post("/auth/forgot-password", dependencies=[Depends(SlidingWindowRateLimiter(limit=30, window_seconds=60))])
async def forgot_password(
    payload: ForgotPasswordRequest, 
    db: Session = Depends(get_db), 
    redis_client: aioredis.Redis = Depends(get_redis)
):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    otp_code = email_verification.generate_otp_code()
    
    # Store verification OTP in Redis instead of the database model
    reset_key = f"reset_password_otp:{payload.email}"
    await redis_client.setex(reset_key, 600, otp_code)

    subject = "Reset your College Connect password"
    html_body = (
        f"<p>Hi,</p>"
        f"<p>Your password reset code is <strong>{otp_code}</strong>.</p>"
        f"<p>Enter this code in the resetting your password.</p>"
        f"<p>If you did not request this, ignore this message.</p>"
    )
    plain_body = (
        f"Hi,\n\n"
        f"Your password reset code is {otp_code}.\n"
        f"Enter this code in the app to reset your password.\n\n"
        f"If you did not request this, ignore this message."
    )

    _send_email_or_dev_fallback(to_address=user.email, subject=subject, html_body=html_body, plain_body=plain_body)

    return {"message": "Password reset code sent to your email."}


@router.post("/auth/reset-password", dependencies=[Depends(SlidingWindowRateLimiter(limit=50, window_seconds=60))])
async def reset_password(
    payload: ResetPasswordRequest, 
    db: Session = Depends(get_db), 
    redis_client: aioredis.Redis = Depends(get_redis)
):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    reset_key = f"reset_password_otp:{payload.email}"
    stored_otp = await redis_client.get(reset_key)
    if not stored_otp or stored_otp != payload.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset code.")

    if len(payload.new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be 72 bytes or fewer.")

    try:
        password_hash = security.get_password_hash(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user.password_hash = password_hash
    # Clear legacy DB columns just in case
    user.reset_password_otp = None
    user.reset_password_otp_expires_at = None
    db.add(user)
    db.commit()

    # Clear OTP from Redis cache
    await redis_client.delete(reset_key)

    return {"message": "Password reset successfully."}


@router.post('/auth/delete-user')
def delete_user(request: DeleteUserRequest, db: Session = Depends(get_db)):
    if settings.ENV.lower() not in {'development', 'dev', 'test'}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='User deletion is only allowed in development mode.',
        )

    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found.')

    profile = db.query(StudentProfile).filter(StudentProfile.user_id == user.id).first()
    if profile:
        db.execute(profile_interests.delete().where(profile_interests.c.profile_id == profile.id))
        db.delete(profile)

    db.delete(user)
    db.commit()

    return {"message": f"Deleted user {request.email}."}
