from pydantic import BaseModel, EmailStr, constr


class UserCreate(BaseModel):
    email: EmailStr
    password: constr(min_length=8)


class RegisterResponse(BaseModel):
    pending_id: str
    message: str


class VerifyRegistrationRequest(BaseModel):
    pending_id: str
    otp: str


class ResendOtpRequest(BaseModel):
    pending_id: str


class DeleteUserRequest(BaseModel):
    email: EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: constr(min_length=8)
