"""SQLAlchemy ORM models for database tables"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import JSON, Enum as SQLEnum, Integer, String, Boolean, DateTime, ForeignKey, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column

from contenthive.models.enumerates import MediaStatus, MediaType, TaskRole, TaskStatus, TaskType, UserStatus

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
    updated_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True, index=True)

class User(Base, TimestampMixin):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[UserStatus] = mapped_column(SQLEnum(UserStatus), default=UserStatus.INACTIVE)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Relationships
    profile: Mapped[Optional["Profile"]] = relationship("Profile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    platforms: Mapped[list["Platform"]] = relationship("Platform", secondary="user_platforms", back_populates="users")
    authors: Mapped[list["Author"]] = relationship("Author", secondary="user_authors", back_populates="users")
    parse_results: Mapped[list["ParseResult"]] = relationship("ParseResult", secondary="user_parse_results", back_populates="users")
    tasks: Mapped[list["MainTask"]] = relationship("MainTask", back_populates="user", cascade="all, delete-orphan")

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
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Relationships
    users: Mapped[list["User"]] = relationship("User", secondary="user_platforms", back_populates="platforms")
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
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('platform_id', 'uid', name='uq_platform_uid'),
    )
    
    # Relationships
    users: Mapped[list["User"]] = relationship("User", secondary="user_authors", back_populates="authors")
    platform: Mapped["Platform"] = relationship("Platform", back_populates="authors")
    parse_results: Mapped[list["ParseResult"]] = relationship("ParseResult", back_populates="author", cascade="all, delete-orphan")


class Media(Base, TimestampMixin):
    __tablename__ = "media"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    type: Mapped[Optional[MediaType]] = mapped_column(SQLEnum(MediaType), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cover: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    media_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cover_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[MediaStatus] = mapped_column(SQLEnum(MediaStatus), default=MediaStatus.PENDING, nullable=False, index=True)

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
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('platform_id', 'pid', name='uq_platform_pid'),
    )
    
    # Relationships
    media_list: Mapped[list["ParseResultMedia"]] = relationship("ParseResultMedia", back_populates="parse_result", cascade="all, delete-orphan", order_by="ParseResultMedia.order")
    platform: Mapped["Platform"] = relationship("Platform", back_populates="parse_results")
    author: Mapped["Author"] = relationship("Author", back_populates="parse_results")
    users: Mapped[list["User"]] = relationship("User", secondary="user_parse_results", back_populates="parse_results")
    tasks: Mapped[list["MainTask"]] = relationship("MainTask", back_populates="parse_result")

class ParseResultMedia(Base):
    __tablename__ = "parse_result_media"
    
    parse_result_id: Mapped[int] = mapped_column(Integer, ForeignKey("parse_results.id", ondelete="CASCADE"), primary_key=True)
    media_id: Mapped[int] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"), primary_key=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # Relationships
    parse_result: Mapped["ParseResult"] = relationship("ParseResult", back_populates="media_list")
    media: Mapped["Media"] = relationship("Media", back_populates="parse_results")


class UserPlatform(Base, TimestampMixin):
    __tablename__ = "user_platforms"
    
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id", ondelete="CASCADE"), primary_key=True)


class UserAuthor(Base, TimestampMixin):
    __tablename__ = "user_authors"
    
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True)


class UserParseResult(Base, TimestampMixin):
    __tablename__ = "user_parse_results"
    
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    parse_result_id: Mapped[int] = mapped_column(Integer, ForeignKey("parse_results.id", ondelete="CASCADE"), primary_key=True)

    # Extension fields can be added here if needed, such as flags or notes related to the user's interaction with the parse result.


class MainTask(Base, TimestampMixin):
    __tablename__ = "main_tasks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    type: Mapped[TaskType] = mapped_column(SQLEnum(TaskType), nullable=False, index=True) # parse_content
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), nullable=False, index=True) # pending, running, canceled, completed, failed, waiting_for_primary
    role: Mapped[Optional[TaskRole]] = mapped_column(SQLEnum(TaskRole), nullable=True) # primary, linked, reused

    url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)

    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)

    primary_task_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("main_tasks.id", ondelete="SET NULL"), nullable=True)
    parse_result_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("parse_results.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tasks")
    parse_result: Mapped[Optional["ParseResult"]] = relationship("ParseResult", back_populates="tasks")
    sub_tasks: Mapped[list["SubTask"]] = relationship("SubTask", back_populates="main_task", cascade="all, delete-orphan")


class SubTask(Base, TimestampMixin):
    __tablename__ = "sub_tasks"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub_task_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    main_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("main_tasks.id", ondelete="CASCADE"), nullable=False)
    
    type: Mapped[TaskType] = mapped_column(SQLEnum(TaskType), nullable=False, index=True) # parser, media_download, content_analysis, etc.
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), nullable=False, index=True) # pending, running, completed, failed

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0) # 0 to 100

    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)

    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(AwareDatetime, nullable=True)

    depends_on_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sub_tasks.id", ondelete="SET NULL"), nullable=True) # for simple dependency management

    # Relationships
    main_task: Mapped["MainTask"] = relationship("MainTask", back_populates="sub_tasks")
    depends_on: Mapped[Optional["SubTask"]] = relationship("SubTask", remote_side=[id], foreign_keys=[depends_on_id])
