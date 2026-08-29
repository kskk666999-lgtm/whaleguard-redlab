from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..audit import write_audit
from ..dependencies import DB, CurrentUser, user_permissions
from ..models import Role, User
from ..schemas import LoginRequest, RoleSummary, TokenResponse, UserResponse
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        created_at=user.created_at,
        updated_at=user.updated_at,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=[
            RoleSummary(
                name=role.name,
                permissions=sorted(permission.code for permission in role.permissions),
            )
            for role in user.roles
        ],
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DB) -> TokenResponse:
    user = db.scalar(
        select(User)
        .where(or_(User.username == payload.username, User.email == payload.username))
        .options(selectinload(User.roles).selectinload(Role.permissions))
    )
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        write_audit(
            db,
            request,
            "auth.login",
            "user",
            outcome="denied",
            details={"username": payload.username},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    user.last_login_at = datetime.now(UTC)
    roles = [role.name for role in user.roles]
    permissions = sorted(user_permissions(user))
    token, csrf_token, expires_in = create_access_token(user.id, roles, permissions)
    write_audit(db, request, "auth.login", "user", user.id, actor=user)
    db.commit()
    return TokenResponse(
        access_token=token,
        csrf_token=csrf_token,
        expires_in=expires_in,
        user=user_response(user),
    )


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser) -> UserResponse:
    return user_response(user)
