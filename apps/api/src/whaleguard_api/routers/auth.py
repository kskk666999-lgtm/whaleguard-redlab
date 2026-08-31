from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from ..audit import write_audit
from ..dependencies import DB, CurrentUser, user_permissions
from ..models import Role, User
from ..schemas import (
    LoginRequest,
    RoleSummary,
    TokenResponse,
    UserPreferences,
    UserPreferencesUpdate,
    UserResponse,
)
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


def user_preferences(user: User) -> UserPreferences:
    try:
        return UserPreferences.model_validate(user.preferences or {})
    except ValidationError:
        return UserPreferences()


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
        preferences=user_preferences(user),
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


@router.get("/preferences", response_model=UserPreferences)
def get_preferences(user: CurrentUser) -> UserPreferences:
    return user_preferences(user)


@router.patch("/preferences", response_model=UserPreferences)
def update_preferences(
    payload: UserPreferencesUpdate,
    request: Request,
    db: DB,
    user: CurrentUser,
) -> UserPreferences:
    current = user_preferences(user)
    updates: dict[str, object] = {}
    if payload.experience_mode is not None:
        updates["experience_mode"] = payload.experience_mode
    if payload.onboarding_complete is not None:
        updates["onboarding_complete"] = payload.onboarding_complete
    if "onboarding_goal" in payload.model_fields_set:
        updates["onboarding_goal"] = payload.onboarding_goal
    updated = current.model_copy(update=updates)
    user.preferences = updated.model_dump(mode="json")
    write_audit(
        db,
        request,
        "user.preferences.update",
        "user",
        user.id,
        actor=user,
        details={
            "experience_mode": updated.experience_mode,
            "onboarding_complete": updated.onboarding_complete,
            "onboarding_goal": updated.onboarding_goal,
        },
    )
    db.commit()
    return updated
