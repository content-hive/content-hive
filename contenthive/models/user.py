from dataclasses import dataclass, field
from datetime import datetime

from pydantic import field_validator

from contenthive.core.secret import secret_manager
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import UserStatus

# Database Models


@dataclass
class UserEntity:
    id: int
    username: str
    password_hash: str
    email: str | None = field(default=None)
    status: UserStatus = field(default=UserStatus.INACTIVE)
    force_password_change: bool = field(default=False)
    is_admin: bool = field(default=False)
    token_version: int = field(default=0)
    last_login_at: datetime | None = field(default=None)
    created_by: int = field(default=0)
    created_at: datetime | None = field(default=None)
    updated_at: datetime | None = field(default=None)


@dataclass
class ProfileEntity:
    user_id: int
    full_name: str | None = field(default=None)
    bio: str | None = field(default=None)
    avatar_url: str | None = field(default=None)
    created_at: datetime | None = field(default=None)
    updated_at: datetime | None = field(default=None)


@dataclass
class SessionEntity:
    id: int
    user_id: int
    device_id: str
    token_jti: str
    created_at: datetime | None = field(default=None)
    last_accessed_at: datetime | None = field(default=None)
    expires_at: datetime | None = field(default=None)
    ip_address: str | None = field(default=None)
    user_agent: str | None = field(default=None)
    revoked: bool = field(default=False)


# Services Models


class DeviceInfoModel(APIBaseModel):
    device_id: str | None = None
    device_name: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


# API request/response Models


class CreateUserRequest(APIBaseModel):
    username: str
    password: str
    email: str | None = None
    is_admin: bool = False

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets strength requirements"""
        if not secret_manager.password_strength(v):
            raise ValueError(
                "Password must be at least 8 characters long and contain "
                "at least one lowercase letter, one uppercase letter, "
                "one digit, and one special character (!@#$%^&*)"
            )
        return v


class UserCreateResponse(APIBaseModel):
    username: str
    password: str
    email: str | None = None
    is_admin: bool = False
    created_by: int

    @classmethod
    def from_entity(cls, user: UserEntity) -> "UserCreateResponse":
        return cls(
            username=user.username,
            password="",  # Password is not included for security reasons
            email=user.email,
            is_admin=user.is_admin,
            created_by=user.created_by,
        )


class LoginRequest(APIBaseModel):
    username: str
    password: str
    client_id: str | None = None
    client_secret: str | None = None


class UserModel(APIBaseModel):
    id: int
    username: str
    email: str | None = None
    is_admin: bool
    status: UserStatus
    force_password_change: bool
    last_login_at: datetime | None = None
    created_by: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_entity(cls, user: UserEntity) -> "UserModel":
        return cls(
            id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin,
            status=user.status,
            force_password_change=user.force_password_change,
            last_login_at=user.last_login_at,
            created_by=user.created_by,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class AuthTokenModel(APIBaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # in seconds


class LoginResponse(APIBaseModel):
    user: UserModel
    tokens: AuthTokenModel


class RefreshTokenRequest(APIBaseModel):
    refresh_token: str


class RefreshTokenResponse(APIBaseModel):
    tokens: AuthTokenModel


class ChangePasswordRequest(APIBaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets strength requirements"""
        if not secret_manager.password_strength(v):
            raise ValueError(
                "Password must be at least 8 characters long and contain "
                "at least one lowercase letter, one uppercase letter, "
                "one digit, and one special character (!@#$%^&*)"
            )
        return v


class UserStatusUpdateRequest(APIBaseModel):
    status: UserStatus


class ResetPasswordResponse(APIBaseModel):
    """Response model for password reset operation"""

    new_password: str


class UserProfileResponse(APIBaseModel):
    user_id: int
    username: str
    email: str | None = None
    is_admin: bool
    status: UserStatus
    last_login_at: datetime | None = None
    full_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    created_by: int
    created_at: datetime | None = None

    @classmethod
    def from_entities(cls, user: UserEntity, profile: ProfileEntity | None) -> "UserProfileResponse":
        return cls(
            user_id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin,
            status=user.status,
            last_login_at=user.last_login_at,
            full_name=profile.full_name if profile else None,
            bio=profile.bio if profile else None,
            avatar_url=profile.avatar_url if profile else None,
            created_by=user.created_by,
            created_at=profile.created_at if profile else None,
        )
