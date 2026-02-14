
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from pydantic import field_validator

from contenthive.core.secret import secret_manager
from contenthive.models.api import BaseEntity

# Database Models

@dataclass
class UserEntity:
    id: int
    username: str
    password_hash: str
    email: Optional[str] = field(default=None)
    status: int = field(default=0)
    force_password_change: bool = field(default=False)
    is_admin: bool = field(default=False)
    token_version: int = field(default=0)
    last_login_at: Optional[datetime] = field(default=None)
    created_by: int = field(default=0)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)

@dataclass
class ProfileEntity:
    user_id: int
    full_name: Optional[str] = field(default=None)
    bio: Optional[str] = field(default=None)
    avatar_url: Optional[str] = field(default=None)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)

@dataclass
class SessionEntity:
    id: int
    user_id: int
    device_id: str
    token_jti: str
    created_at: Optional[datetime] = field(default=None)
    last_accessed_at: Optional[datetime] = field(default=None)
    expires_at: Optional[datetime] = field(default=None)
    ip_address: Optional[str] = field(default=None)
    user_agent: Optional[str] = field(default=None)
    revoked: bool = field(default=False)

# Services Models

class DeviceInfoModel(BaseEntity):
    device_id: Optional[str] = None
    device_name: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

# API request/response Models

class CreateUserRequest(BaseEntity):
    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets strength requirements"""
        if not secret_manager.password_strength(v):
            raise ValueError(
                'Password must be at least 8 characters long and contain '
                'at least one lowercase letter, one uppercase letter, '
                'one digit, and one special character (!@#$%^&*)'
            )
        return v

class UserCreateResponse(BaseEntity):
    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False
    created_by: int

    @classmethod
    def from_entity(cls, user: UserEntity) -> 'UserCreateResponse':
        return cls(
            username=user.username,
            password="",  # Password is not included for security reasons
            email=user.email,
            is_admin=user.is_admin,
            created_by=user.created_by
        )

class LoginRequest(BaseEntity):
    username: str
    password: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

class UserModel(BaseEntity):
    id: int
    username: str
    email: Optional[str] = None
    is_admin: bool
    status: int
    force_password_change: bool
    last_login_at: Optional[datetime] = None
    created_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_entity(cls, user: UserEntity) -> 'UserModel':
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
            updated_at=user.updated_at
        )

class AuthTokenModel(BaseEntity):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # in seconds

class LoginResponse(BaseEntity):
    user: UserModel
    tokens: AuthTokenModel

class RefreshTokenRequest(BaseEntity):
    refresh_token: str

class RefreshTokenResponse(BaseEntity):
    tokens: AuthTokenModel

class ChangePasswordRequest(BaseEntity):
    new_password: str

    @field_validator('new_password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets strength requirements"""
        if not secret_manager.password_strength(v):
            raise ValueError(
                'Password must be at least 8 characters long and contain '
                'at least one lowercase letter, one uppercase letter, '
                'one digit, and one special character (!@#$%^&*)'
            )
        return v

class UserStatusUpdateRequest(BaseEntity):
    status: Literal[0, 1, 2]  # 0 = inactive, 1 = active, 2 = disabled

class UserProfileResponse(BaseEntity):
    user_id: int
    username: str
    email: Optional[str] = None
    is_admin: bool
    status: int
    last_login_at: Optional[datetime] = None
    full_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    created_by: int
    created_at: Optional[datetime] = None

    @classmethod
    def from_entities(cls, user: UserEntity, profile: Optional[ProfileEntity]) -> 'UserProfileResponse':
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
            created_at=profile.created_at if profile else None
        )