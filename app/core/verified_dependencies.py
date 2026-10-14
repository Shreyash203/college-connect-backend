from fastapi import Depends, HTTPException, status
from app.core.dependencies import AuthenticatedUser, get_current_user


def get_current_verified_user(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address must be verified to access this resource.",
        )
    return current_user
