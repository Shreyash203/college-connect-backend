from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core import email_client, email_verification, security
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User, StudentProfile, profile_interests, PendingRegistration
from app.schemas.auth import (
    DeleteUserRequest,
    UserCreate,
    Token,
    RegisterResponse,
    VerifyRegistrationRequest,
    ResendOtpRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
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


@router.post("/auth/register", response_model=RegisterResponse)
def register(user_create: UserCreate, db: Session = Depends(get_db)):
    allowed_domains = [d.strip().lower() for d in settings.AUTHORIZED_EMAIL_DOMAINS.split(",") if d.strip()]
    email_domain = user_create.email.split("@")[-1].lower()
    if email_domain not in allowed_domains:
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

    existing_pending = db.query(PendingRegistration).filter(PendingRegistration.email == user_create.email).first()
    if existing_pending:
        db.delete(existing_pending)
        db.commit()

    try:
        password_hash = security.get_password_hash(user_create.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    otp_code = email_verification.generate_otp_code()

    pending = PendingRegistration(
        email=user_create.email,
        password_hash=password_hash,
        otp=otp_code,
        otp_expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.add(pending)
    db.commit()
    db.refresh(pending)

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

    _send_email_or_dev_fallback(to_address=pending.email, subject=subject, html_body=html_body, plain_body=plain_body)

    return RegisterResponse(pending_id=pending.id, message="Registration initiated. Check your email for the verification code.")


@router.post("/auth/verify-registration", response_model=Token)
def verify_registration(payload: VerifyRegistrationRequest, db: Session = Depends(get_db)):
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == payload.pending_id).first()
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration request not found.")

    if pending.otp != payload.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code.")

    if datetime.utcnow() > pending.otp_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code expired.")

    existing_user = db.query(User).filter(User.email == pending.email).first()
    if existing_user:
        db.delete(pending)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    user = User(
        email=pending.email,
        password_hash=pending.password_hash,
        is_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.delete(pending)
    db.commit()

    access_token = security.create_access_token(subject=str(user.id))
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.id}


@router.post("/auth/resend-otp")
def resend_otp(payload: ResendOtpRequest, db: Session = Depends(get_db)):
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == payload.pending_id).first()
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration request not found.")

    new_otp = email_verification.generate_otp_code()
    pending.otp = new_otp
    pending.otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.add(pending)
    db.commit()

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

    _send_email_or_dev_fallback(to_address=pending.email, subject=subject, html_body=html_body, plain_body=plain_body)

    return {"message": "A new verification code has been sent to your email."}


@router.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
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
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    otp_code = email_verification.generate_otp_code()
    user.reset_password_otp = otp_code
    user.reset_password_otp_expires_at = datetime.utcnow() + timedelta(minutes=10)
    db.add(user)
    db.commit()

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


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user.reset_password_otp or user.reset_password_otp != payload.otp:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset code.")

    if not user.reset_password_otp_expires_at or datetime.utcnow() > user.reset_password_otp_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset code expired.")

    if len(payload.new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be 72 bytes or fewer.")

    try:
        password_hash = security.get_password_hash(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user.password_hash = password_hash
    user.reset_password_otp = None
    user.reset_password_otp_expires_at = None
    db.add(user)
    db.commit()

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
