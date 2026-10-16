from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.orm import Session

from .config import (
    AUTH_TOKEN_ALGORITHM,
    AUTH_TOKEN_EXPIRE_SECONDS,
    ConfigurationError,
    get_auth_token_secret,
)
from .database import get_db
from .models import User


AUTHENTICATION_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="认证凭证无效或已过期",
    headers={"WWW-Authenticate": "Bearer"},
)


def create_access_token(user: User, *, now: datetime | None = None) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=AUTH_TOKEN_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, get_auth_token_secret(), algorithm=AUTH_TOKEN_ALGORITHM)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise AUTHENTICATION_ERROR
    try:
        payload = jwt.decode(
            token.strip(),
            get_auth_token_secret(),
            algorithms=[AUTH_TOKEN_ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        raw_user_id = payload.get("sub")
        if not isinstance(raw_user_id, str) or not raw_user_id.isdigit():
            raise InvalidTokenError("invalid subject")
        user = db.get(User, int(raw_user_id))
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ExpiredSignatureError, InvalidTokenError):
        raise AUTHENTICATION_ERROR
    if user is None:
        raise AUTHENTICATION_ERROR
    return user


def require_leader(current_user: User = Depends(get_current_user)) -> User:
    """Require the user's current database role to be leader."""
    if current_user.role != "leader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号没有团长权限")
    return current_user
