"""SQLAlchemy ORM models for database tables"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, Boolean, DateTime, ForeignKey, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column

Base = declarative_base()


class AwareDatetime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value
    
    
class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)

class User(Base, TimestampMixin):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[int] = mapped_column(Integer, default=0)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Relationships
    profile: Mapped[Optional["Profile"]] = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    platforms: Mapped[list["Platform"]] = relationship("Platform", back_populates="user", cascade="all, delete-orphan")
    authors: Mapped[list["Author"]] = relationship("Author", back_populates="user", cascade="all, delete-orphan")
    parse_results: Mapped[list["ParseResult"]] = relationship("ParseResult", back_populates="user", cascade="all, delete-orphan")


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"
    
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="profile")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    token_jti: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(AwareDatetime, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_accessed_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(timezone.utc))
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'device_id', name='uq_user_device'),
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Platform(Base, TimestampMixin):
    __tablename__ = "platforms"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'code', name='uq_user_platform'),
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="platforms")
    authors: Mapped[list["Author"]] = relationship("Author", back_populates="platform", cascade="all, delete-orphan")
    parse_results: Mapped[list["ParseResult"]] = relationship("ParseResult", back_populates="platform", cascade="all, delete-orphan")


class Author(Base, TimestampMixin):
    __tablename__ = "authors"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"), nullable=False)
    uid: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'platform_id', 'uid', name='uq_user_platform_uid'),
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="authors")
    platform: Mapped["Platform"] = relationship("Platform", back_populates="authors")
    parse_results: Mapped[list["ParseResult"]] = relationship("ParseResult", back_populates="author", cascade="all, delete-orphan")


class Media(Base, TimestampMixin):
    __tablename__ = "media"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cover: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    media_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cover_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Relationships
    parse_results: Mapped[list["ParseResultMedia"]] = relationship("ParseResultMedia", back_populates="media", cascade="all, delete-orphan")


class ParseResult(Base, TimestampMixin):
    __tablename__ = "parse_results"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pid: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("authors.id"), nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"), nullable=False)
    post_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parser: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('user_id', 'platform_id', 'pid', name='uq_user_platform_pid'),
    )
    
    # Relationships
    media_list: Mapped[list["ParseResultMedia"]] = relationship("ParseResultMedia", back_populates="parse_result", cascade="all, delete-orphan")
    platform: Mapped["Platform"] = relationship("Platform", back_populates="parse_results")
    author: Mapped["Author"] = relationship("Author", back_populates="parse_results")
    user: Mapped["User"] = relationship("User", back_populates="parse_results")

class ParseResultMedia(Base):
    __tablename__ = "parse_result_media"
    
    parse_result_id: Mapped[int] = mapped_column(Integer, ForeignKey("parse_results.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[int] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"), primary_key=True)
    
    # Relationships
    parse_result: Mapped["ParseResult"] = relationship("ParseResult", back_populates="media_list")
    media: Mapped["Media"] = relationship("Media", back_populates="parse_results")
