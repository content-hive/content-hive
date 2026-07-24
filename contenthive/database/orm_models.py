"""SQLAlchemy ORM models for database tables"""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

from contenthive.models.enumerates import (
    MediaStatus,
    MediaType,
    ParserResultStatus,
    TagEffect,
    TaskRole,
    TaskStatus,
    TaskType,
    UserStatus,
)

Base = declarative_base()


class AwareDatetime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return value.replace(tzinfo=UTC)
        return value


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        AwareDatetime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True, index=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[UserStatus] = mapped_column(SQLEnum(UserStatus), default=UserStatus.INACTIVE, nullable=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    profile: Mapped[Optional["Profile"]] = relationship(
        "Profile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    platforms: Mapped[list["Platform"]] = relationship("Platform", secondary="user_platforms", back_populates="users")
    authors: Mapped[list["Author"]] = relationship("Author", secondary="user_authors", back_populates="users")
    parse_results: Mapped[list["ParseResult"]] = relationship(
        "ParseResult", secondary="user_parse_results", back_populates="users"
    )
    tags: Mapped[list["Tag"]] = relationship("Tag", back_populates="user", cascade="all, delete-orphan")
    tasks: Mapped[list["MainTask"]] = relationship("MainTask", back_populates="user", cascade="all, delete-orphan")


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="profile")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(String, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    token_jti: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(AwareDatetime, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    last_accessed_at: Mapped[datetime] = mapped_column(AwareDatetime, default=lambda: datetime.now(UTC), nullable=False)

    # Unique constraint
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_user_device"),)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Platform(Base, TimestampMixin):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    icon_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    users: Mapped[list["User"]] = relationship("User", secondary="user_platforms", back_populates="platforms")
    authors: Mapped[list["Author"]] = relationship("Author", back_populates="platform", cascade="all, delete-orphan")
    parse_results: Mapped[list["ParseResult"]] = relationship(
        "ParseResult", back_populates="platform", cascade="all, delete-orphan"
    )


class Author(Base, TimestampMixin):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"), nullable=False)
    uid: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_path: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    banner: Mapped[str | None] = mapped_column(String, nullable=True)
    banner_path: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)

    # Unique constraint
    __table_args__ = (UniqueConstraint("platform_id", "uid", name="uq_platform_uid"),)

    # Relationships
    users: Mapped[list["User"]] = relationship("User", secondary="user_authors", back_populates="authors")
    platform: Mapped["Platform"] = relationship("Platform", back_populates="authors")
    parse_results: Mapped[list["ParseResult"]] = relationship(
        "ParseResult", back_populates="author", cascade="all, delete-orphan"
    )


class Media(Base, TimestampMixin):
    __tablename__ = "media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    parse_result_id: Mapped[int] = mapped_column(Integer, ForeignKey("parse_results.id"), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    url: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[MediaType | None] = mapped_column(SQLEnum(MediaType), nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover: Mapped[str | None] = mapped_column(String, nullable=True)
    url_fallbacks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cover_fallbacks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    media_path: Mapped[str | None] = mapped_column(String, nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        SQLEnum(MediaStatus), default=MediaStatus.PENDING, nullable=False, index=True
    )

    # Unique constraint: media URLs are unique within a single parse result
    __table_args__ = (UniqueConstraint("parse_result_id", "url", name="uq_parse_result_url"),)

    # Relationships
    parse_result: Mapped["ParseResult"] = relationship("ParseResult", back_populates="media")


class ParseResult(Base, TimestampMixin):
    __tablename__ = "parse_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    pid: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str | None] = mapped_column(String, nullable=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("authors.id"), nullable=False)
    platform_id: Mapped[int] = mapped_column(Integer, ForeignKey("platforms.id"), nullable=False)
    post_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[ParserResultStatus] = mapped_column(SQLEnum(ParserResultStatus), nullable=False)

    # Unique constraint
    __table_args__ = (UniqueConstraint("platform_id", "pid", name="uq_platform_pid"),)

    # Relationships
    media: Mapped[list["Media"]] = relationship(
        "Media",
        back_populates="parse_result",
        cascade="all, delete-orphan",
        order_by="Media.order",
    )
    platform: Mapped["Platform"] = relationship("Platform", back_populates="parse_results")
    author: Mapped["Author"] = relationship("Author", back_populates="parse_results")
    users: Mapped[list["User"]] = relationship("User", secondary="user_parse_results", back_populates="parse_results")
    tasks: Mapped[list["MainTask"]] = relationship("MainTask", back_populates="parse_result")


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_tag_name"),)

    user: Mapped["User"] = relationship("User", back_populates="tags")
    effects: Mapped[list["UserTagEffect"]] = relationship(
        "UserTagEffect", back_populates="tag", cascade="all, delete-orphan"
    )


class UserTagEffect(Base, TimestampMixin):
    """Per-user display effects for a vocabulary tag (one row per effect; no rows means none)."""

    __tablename__ = "user_tag_effects"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    effect: Mapped[TagEffect] = mapped_column(
        SQLEnum(TagEffect, values_callable=lambda obj: [e.value for e in obj]),
        primary_key=True,
        nullable=False,
    )

    tag: Mapped["Tag"] = relationship("Tag", back_populates="effects")


class UserPlatform(Base, TimestampMixin):
    __tablename__ = "user_platforms"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    platform_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("platforms.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )


class UserAuthor(Base, TimestampMixin):
    __tablename__ = "user_authors"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    author_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("authors.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    # Per-user tag IDs referencing the tags table (JSON list of ints).
    tags: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)


class UserParseResult(Base, TimestampMixin):
    __tablename__ = "user_parse_results"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    parse_result_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("parse_results.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    # Per-user tag IDs referencing the tags table (JSON list of ints).
    tags: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)


class UserMedia(Base, TimestampMixin):
    __tablename__ = "user_media"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    media_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("media.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    # Per-user tag IDs referencing the tags table (JSON list of ints).
    tags: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)


class MainTask(Base, TimestampMixin):
    __tablename__ = "main_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    type: Mapped[TaskType] = mapped_column(SQLEnum(TaskType), nullable=False, index=True)  # parse_content
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus), nullable=False, index=True
    )  # pending, running, canceled, completed, failed, waiting_for_primary
    role: Mapped[TaskRole | None] = mapped_column(SQLEnum(TaskRole), nullable=True)  # primary, linked, reused

    url: Mapped[str] = mapped_column(String, nullable=False, index=True)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)

    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True)

    primary_task_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("main_tasks.id", ondelete="SET NULL"), nullable=True
    )
    parse_result_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("parse_results.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="tasks")
    parse_result: Mapped[Optional["ParseResult"]] = relationship("ParseResult", back_populates="tasks")
    sub_tasks: Mapped[list["SubTask"]] = relationship(
        "SubTask", back_populates="main_task", cascade="all, delete-orphan"
    )


class SubTask(Base, TimestampMixin):
    __tablename__ = "sub_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub_task_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    main_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("main_tasks.id", ondelete="CASCADE"), nullable=False)

    type: Mapped[TaskType] = mapped_column(
        SQLEnum(TaskType), nullable=False, index=True
    )  # parser, media_download, content_analysis, etc.
    status: Mapped[TaskStatus] = mapped_column(
        SQLEnum(TaskStatus), nullable=False, index=True
    )  # pending, running, completed, failed

    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 to 100

    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)

    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(AwareDatetime, nullable=True)

    depends_on_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sub_tasks.id", ondelete="SET NULL"), nullable=True
    )  # for simple dependency management

    # Relationships
    main_task: Mapped["MainTask"] = relationship("MainTask", back_populates="sub_tasks")
    depends_on: Mapped[Optional["SubTask"]] = relationship("SubTask", remote_side=[id], foreign_keys=[depends_on_id])
