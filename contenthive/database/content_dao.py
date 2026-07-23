from datetime import UTC, datetime

from sqlalchemy import Integer, cast, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import (
    Author,
    Media,
    ParseResult,
    Platform,
    Tag,
    UserAuthor,
    UserMedia,
    UserParseResult,
    UserPlatform,
)
from contenthive.logger import logger
from contenthive.models.content import (
    AuthorEntity,
    DownloadedMediaInfo,
    MediaEntity,
    ParseResultEntity,
    PlatformEntity,
    TagEntity,
)
from contenthive.models.enumerates import MediaStatus
from contenthive.plugins.contracts import (
    ParserAuthorInfo,
    ParserMediaInfo,
    ParserPlatformInfo,
    ParserResult,
)
from contenthive.utils.content import ContentDirectory, resolve_content_id


def normalize_tag_name(name: str) -> str:
    """Trim tag name whitespace."""
    return name.strip()


def normalize_tag_names(names: list[str]) -> list[str]:
    """
    Normalize tag names: trim, drop empties, dedupe while preserving order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        normalized = normalize_tag_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


class ContentDAO:
    """
    Data Access Object for parser-related database operations.
    """

    def __init__(self):
        self.engine = get_engine()
        self.SessionLocal = get_session_local()
        self.session = None

    def __enter__(self):
        self.session = self.SessionLocal()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_session(self) -> Session:
        """Get database session"""
        if self.session is None:
            self.session = self.SessionLocal()
        return self.session

    def close(self):
        """Close database session"""
        if self.session:
            self.session.close()
            self.session = None

    def save_platform(self, platform: ParserPlatformInfo, user_id: int, commit: bool = False) -> int:
        """
        Save or update platform information and create user association.

        Args:
            platform: Platform entity
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns platform_id.
        """
        session = self._get_session()
        try:
            # Check if platform exists globally by code
            stmt = select(Platform).where(Platform.code == platform.code)
            existing_platform = session.execute(stmt).scalar_one_or_none()

            if existing_platform:
                # Update existing platform
                existing_platform.name = platform.name
                existing_platform.url = str(platform.url)
                existing_platform.icon_url = str(platform.icon_url) if platform.icon_url else None
                # Restore if soft-deleted
                if existing_platform.deleted_at is not None:
                    existing_platform.deleted_at = None
                    logger.info(f"Restored soft-deleted platform {existing_platform.id}")
                session.flush()
                platform_id = existing_platform.id
            else:
                # Insert new platform
                new_platform = Platform(
                    code=platform.code,
                    name=platform.name,
                    url=str(platform.url),
                    icon_url=str(platform.icon_url) if platform.icon_url else None,
                )
                session.add(new_platform)
                session.flush()
                platform_id = new_platform.id

            # Create or update user-platform association
            stmt = select(UserPlatform).where(
                (UserPlatform.user_id == user_id) & (UserPlatform.platform_id == platform_id)
            )
            user_platform = session.execute(stmt).scalar_one_or_none()

            if not user_platform:
                # Create new association
                user_platform = UserPlatform(user_id=user_id, platform_id=platform_id)
                session.add(user_platform)
                session.flush()
            elif user_platform.deleted_at is not None:
                # Restore soft-deleted association
                user_platform.deleted_at = None
                session.flush()

            if commit:
                session.commit()

            return platform_id
        except Exception as e:
            if commit:
                session.rollback()
            raise Exception(f"Failed to save platform: {e}") from e

    def save_author(
        self,
        author: ParserAuthorInfo,
        platform_id: int,
        user_id: int,
        commit: bool = False,
    ) -> int:
        """
        Save or update author information and create user association.

        Args:
            author: Author entity
            platform_id: Platform ID
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns author_id.
        """
        session = self._get_session()
        try:
            # Check if author exists globally by platform_id + uid
            stmt = select(Author).where((Author.platform_id == platform_id) & (Author.uid == author.uid))
            existing_author = session.execute(stmt).scalar_one_or_none()

            if existing_author:
                # Update existing author
                existing_author.name = author.name
                existing_author.username = author.username
                existing_author.avatar = str(author.avatar) if author.avatar else None
                existing_author.url = str(author.url) if author.url else None
                existing_author.banner = str(author.banner) if author.banner else None
                existing_author.description = author.description
                # Restore if soft-deleted
                if existing_author.deleted_at is not None:
                    existing_author.deleted_at = None
                    logger.info(f"Restored soft-deleted author {existing_author.id}")
                session.flush()
                author_id = existing_author.id
            else:
                # Insert new author
                new_author = Author(
                    platform_id=platform_id,
                    uid=author.uid,
                    name=author.name,
                    username=author.username,
                    avatar=str(author.avatar) if author.avatar else None,
                    url=str(author.url) if author.url else None,
                    banner=str(author.banner) if author.banner else None,
                    description=author.description,
                )
                session.add(new_author)
                session.flush()
                author_id = new_author.id

            # Create or update user-author association
            stmt = select(UserAuthor).where((UserAuthor.user_id == user_id) & (UserAuthor.author_id == author_id))
            user_author = session.execute(stmt).scalar_one_or_none()

            if not user_author:
                # Create new association
                user_author = UserAuthor(user_id=user_id, author_id=author_id)
                session.add(user_author)
                session.flush()
            elif user_author.deleted_at is not None:
                # Restore soft-deleted association
                user_author.deleted_at = None
                session.flush()

            if commit:
                session.commit()

            return author_id
        except Exception as e:
            if commit:
                session.rollback()
            raise Exception(f"Failed to save author: {e}") from e

    def get_author_profile_state(self, platform_code: str, uid: str) -> AuthorEntity | None:
        """
        Fetch an author by platform code and uid, returning the full entity.

        Intended to be called BEFORE save_parse_result overwrites the avatar/banner
        URLs, so the caller can detect whether the remote URL changed.

        Args:
            platform_code: Platform code (e.g. "twitter")
            uid: Author uid on the platform

        Returns:
            AuthorEntity if the author exists, otherwise None.
        """
        session = self._get_session()
        stmt = (
            select(Author)
            .join(Platform, Author.platform_id == Platform.id)
            .where((Platform.code == platform_code) & (Author.uid == uid))
        )
        author = session.execute(stmt).scalar_one_or_none()
        if author is None:
            return None
        return AuthorEntity.from_orm(author)

    def update_author_profile_paths(
        self,
        author_id: int,
        avatar_path: str | None = None,
        banner_path: str | None = None,
        commit: bool = True,
    ) -> None:
        """
        Update an author's local avatar/banner paths.

        Only the provided (non-None) paths are written; passing None leaves the
        corresponding column unchanged so previously downloaded assets are kept.

        Args:
            author_id: Author ID
            avatar_path: New local avatar path (/media/...), or None to leave unchanged
            banner_path: New local banner path (/media/...), or None to leave unchanged
            commit: Whether to commit immediately (default: True)
        """
        if avatar_path is None and banner_path is None:
            return

        session = self._get_session()
        try:
            author = session.get(Author, author_id)
            if author is None:
                logger.warning(f"Cannot update profile paths: author {author_id} not found")
                return
            if avatar_path is not None:
                author.avatar_path = avatar_path
            if banner_path is not None:
                author.banner_path = banner_path
            session.flush()
            if commit:
                session.commit()
        except Exception as e:
            if commit:
                session.rollback()
            raise Exception(f"Failed to update author profile paths: {e}") from e

    def _save_media(self, media: MediaEntity, parse_result_id: int, order: int = 0, commit: bool = False) -> int:
        """
        Save media information for a specific parse result.

        Media is owned by a single parse result (one-to-many). Deduplication is
        scoped to (parse_result_id, url) so downloaded media can update the row
        created during the parse phase.

        Args:
            media: Media entity
            parse_result_id: Owning parse result ID
            order: Display order within the parse result (default: 0)
            commit: Commit immediately after inserting a new media row (default: False)

        Returns media_id.
        """
        session = self._get_session()
        try:
            # Check if media exists within this parse result
            stmt = select(Media).where((Media.parse_result_id == parse_result_id) & (Media.url == media.url))
            existing_media = session.execute(stmt).scalar_one_or_none()

            if existing_media:
                # Only update status if:
                # 1. We have new media/cover paths (successful download), or
                # 2. Current status is 'pending' (allow first status update)
                if media.media_path or media.cover_path:
                    # Successful download - update everything
                    existing_media.status = media.status
                    if media.duration:
                        existing_media.duration = media.duration
                    if media.width:
                        existing_media.width = media.width
                    if media.height:
                        existing_media.height = media.height
                    if media.media_path:
                        existing_media.media_path = media.media_path
                    if media.cover_path:
                        existing_media.cover_path = media.cover_path
                    session.flush()
                elif existing_media.status == MediaStatus.PENDING:
                    # Allow status update from pending to failed/other
                    existing_media.status = media.status
                    session.flush()
                # else: Don't overwrite completed/failed status without new files
                return existing_media.id

            # Insert new media
            new_media = Media(
                parse_result_id=parse_result_id,
                order=order,
                url=media.url,
                type=media.type,
                title=media.title,
                cover=media.cover,
                url_fallbacks=media.url_fallbacks,
                cover_fallbacks=media.cover_fallbacks,
                duration=media.duration,
                width=media.width,
                height=media.height,
                media_path=media.media_path,
                cover_path=media.cover_path,
                status=media.status,
            )
            session.add(new_media)
            session.flush()
            media_id = new_media.id

            if commit:
                session.commit()

            return media_id
        except Exception as e:
            if commit:
                session.rollback()
            raise Exception(f"Failed to save media: {e}") from e

    def save_medias(self, medias: list[ParserMediaInfo], parse_result_id: int, commit: bool = False) -> list[int]:
        """
        Save multiple media entities for a parse result.

        Args:
            medias: List of ParserMediaInfo objects
            parse_result_id: Owning parse result ID
            commit: Whether to commit immediately (default: False)

        Returns list of media_ids.
        """
        media_ids = []
        for order, media in enumerate(medias):
            media_entity = MediaEntity(
                status=MediaStatus.PENDING,  # Default to pending when saving from parser result
                url=str(media.url),
                type=media.type if media.type else None,
                title=media.title,
                cover=str(media.cover) if media.cover else None,
                url_fallbacks=[str(u) for u in (media.url_fallbacks or [])],
                cover_fallbacks=[str(u) for u in (media.cover_fallbacks or [])],
            )
            media_id = self._save_media(media_entity, parse_result_id, order=order, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_session().commit()

        return media_ids

    def save_downloaded_medias(
        self, medias: list[DownloadedMediaInfo], parse_result_id: int, commit: bool = False
    ) -> list[int]:
        """
        Save multiple downloaded media entities for a parse result.

        Updates the rows created during the parse phase (matched by
        (parse_result_id, url)) with download status and local paths.

        Args:
            medias: List of DownloadedMediaInfo objects
            parse_result_id: Owning parse result ID
            commit: Whether to commit immediately (default: False)

        Returns list of media_ids.
        """
        media_ids = []
        for order, media in enumerate(medias):
            media_entity = MediaEntity(
                status=media.status,
                url=str(media.url),
                type=media.type if media.type else None,
                title=media.title,
                cover=str(media.cover) if media.cover else None,
                url_fallbacks=[str(u) for u in media.url_fallbacks],
                cover_fallbacks=[str(u) for u in media.cover_fallbacks],
                duration=media.duration,
                width=media.width,
                height=media.height,
                media_path=media.media_path,
                cover_path=media.cover_path,
            )
            media_id = self._save_media(media_entity, parse_result_id, order=order, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_session().commit()

        return media_ids

    def save_parse_result(self, result: ParserResult, user_id: int) -> int:
        """
        Save complete parse result including platform, author, media and user association.
        Uses a single transaction for all operations.

        Args:
            result: ParserResult from parser
            user_id: User ID

        Returns the saved parse result ID.
        """
        session = self._get_session()
        try:
            # Save platform and get ID
            platform_id = self.save_platform(result.platform, user_id, commit=False)

            # Save author and get ID
            author_id = self.save_author(result.author, platform_id, user_id, commit=False)

            # Check if parse result already exists globally by platform_id + pid
            stmt = select(ParseResult).where((ParseResult.pid == result.pid) & (ParseResult.platform_id == platform_id))
            existing_result = session.execute(stmt).scalar_one_or_none()

            if existing_result:
                parse_result_id = existing_result.id
                # Update existing parse result
                existing_result.url = str(result.url)
                existing_result.title = result.title
                existing_result.content = result.content
                existing_result.post_time = result.post_time
                existing_result.parser = result.parser
                existing_result.state = result.state
                existing_result.author_id = author_id
                # Restore if soft-deleted
                if existing_result.deleted_at is not None:
                    existing_result.deleted_at = None
                    logger.info(f"Restored soft-deleted parse result {existing_result.id}")
                session.flush()

                # Clear old media rows (one-to-many: media belongs to this parse result)
                session.query(Media).filter(Media.parse_result_id == parse_result_id).delete()
            else:
                # Insert new parse result
                new_result = ParseResult(
                    pid=result.pid,
                    url=str(result.url),
                    title=result.title,
                    content=result.content,
                    author_id=author_id,
                    platform_id=platform_id,
                    post_time=result.post_time,
                    parser=result.parser,
                    state=result.state,
                )
                session.add(new_result)
                session.flush()
                parse_result_id = new_result.id

            # Create or update user-parse_result association
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id) & (UserParseResult.parse_result_id == parse_result_id)
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()

            if not user_parse_result:
                # Create new association
                user_parse_result = UserParseResult(user_id=user_id, parse_result_id=parse_result_id)
                session.add(user_parse_result)
                session.flush()
            elif user_parse_result.deleted_at is not None:
                # Restore soft-deleted association
                user_parse_result.deleted_at = None
                session.flush()
            else:
                # Update updated_at to reflect re-parse, ensures sync detects the change
                user_parse_result.updated_at = datetime.now(UTC)
                session.flush()

            # Save media rows owned by this parse result
            self.save_medias(result.media, parse_result_id, commit=False)

            # Commit all changes
            session.commit()

            return parse_result_id
        except Exception as e:
            session.rollback()
            raise Exception(
                f"Failed to save parse result (pid: {result.pid}, platform: {result.platform.code}): {e}"
            ) from e

    def get_parse_result(self, parse_result_id: int, user_id: int) -> ParseResultEntity:
        """
        Get parse result entity by ID.
        Checks if the user has access to this result.
        Returns ParseResultEntity object.
        """
        session = self._get_session()

        # Query with user access check through UserParseResult
        query = (
            session.query(ParseResult)
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == ParseResult.id)
                & (UserParseResult.user_id == user_id)
                & (UserParseResult.deleted_at.is_(None)),
            )
            .filter(ParseResult.id == parse_result_id, ParseResult.deleted_at.is_(None))
        )

        result_orm = query.first()
        if not result_orm:
            raise ValueError(f"Parse result with id {parse_result_id} not found or access denied")

        stmt = select(UserParseResult).where(
            (UserParseResult.user_id == user_id) & (UserParseResult.parse_result_id == parse_result_id)
        )
        user_parse_result = session.execute(stmt).scalar_one_or_none()
        tags = self._resolve_tags_for_ids(user_id, list(user_parse_result.tags or []) if user_parse_result else [])
        entity = ParseResultEntity.from_orm(result_orm, tags=tags)
        media_ids = [media.id for media in result_orm.media]
        self._apply_media_tags_to_entity(entity, self._load_media_tags_map(user_id, media_ids))
        self._apply_author_tags_to_entity(entity, self._load_author_tags_map(user_id, [result_orm.author_id]))
        return entity

    def find_parse_result_by_url(self, url: str) -> ParseResultEntity | None:
        """
        Find parse result by URL (globally, without user filtering).
        Used for task deduplication.

        Args:
            url: URL to search for

        Returns:
            ParseResultEntity object if found, None otherwise
        """
        session = self._get_session()

        stmt = select(ParseResult).where(ParseResult.url == url, ParseResult.deleted_at.is_(None))

        result_orm = session.execute(stmt).scalar_one_or_none()
        return ParseResultEntity.from_orm(result_orm) if result_orm else None

    def list_parse_results(
        self,
        user_id: int,
        platform_id: int | None = None,
        author_id: int | None = None,
        tag_id: int | None = None,
        exclude_tag_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[ParseResultEntity], int]:
        """
        List parse results with pagination and sorting.

        Args:
            user_id: Filter by user ID
            platform_id: Filter by platform ID
            author_id: Filter by author ID
            tag_id: Only include content that has this tag ID
            exclude_tag_id: Exclude content that has this tag ID
            limit: Maximum number of results to return
            offset: Number of results to skip
            sort_by: Field to sort by (id, created_at, updated_at)
            order: Sort order (asc, desc)

        Returns tuple of (list of ParseResultEntity objects, total count).
        """
        session = self._get_session()

        # Build query with JOIN to UserParseResult
        query = (
            select(ParseResult)
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == ParseResult.id)
                & (UserParseResult.user_id == user_id)
                & (UserParseResult.deleted_at.is_(None)),
            )
            .where(ParseResult.deleted_at.is_(None))
        )

        if platform_id is not None:
            query = query.where(ParseResult.platform_id == platform_id)

        if author_id is not None:
            query = query.where(ParseResult.author_id == author_id)

        query = self._apply_tag_filters(query, tag_id=tag_id, exclude_tag_id=exclude_tag_id)

        # Get total count
        count_query = (
            select(func.count(ParseResult.id))
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == ParseResult.id)
                & (UserParseResult.user_id == user_id)
                & (UserParseResult.deleted_at.is_(None)),
            )
            .where(ParseResult.deleted_at.is_(None))
        )
        if platform_id is not None:
            count_query = count_query.where(ParseResult.platform_id == platform_id)
        if author_id is not None:
            count_query = count_query.where(ParseResult.author_id == author_id)
        count_query = self._apply_tag_filters(count_query, tag_id=tag_id, exclude_tag_id=exclude_tag_id)
        total = session.execute(count_query).scalar() or 0

        # Add sorting
        if sort_by == "post_time":
            sort_field = ParseResult.post_time
        elif sort_by == "updated_at":
            sort_field = ParseResult.updated_at
        elif sort_by == "id":
            sort_field = ParseResult.id
        else:
            sort_field = ParseResult.created_at

        query = query.order_by(sort_field.asc()) if order.lower() == "asc" else query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        results_orm = session.execute(query).scalars().all()

        return self._entities_with_user_tags(user_id, list(results_orm)), total

    def sync_parse_results(
        self,
        user_id: int,
        last_sync_time: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ParseResultEntity], int]:
        """
        Sync parse results based on last sync time.
        Returns all parse results (including deleted ones in association table)
        that were created or updated after the last sync time.

        Args:
            user_id: Filter by user ID
            last_sync_time: Optional datetime of the last sync. If None, returns all results.
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns tuple of (list of ParseResultEntity objects with deleted_at field, total count).
        """
        session = self._get_session()

        # Build query with JOIN to UserParseResult (include soft-deleted associations)
        # Eagerly load media to avoid N+1 lazy-load queries per result
        query = (
            select(ParseResult)
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == ParseResult.id) & (UserParseResult.user_id == user_id),
            )
            .options(selectinload(ParseResult.media))
        )

        # Filter by last_sync_time if provided
        if last_sync_time is not None:
            media_update_subquery = exists(
                select(1)
                .select_from(Media)
                .where(
                    Media.parse_result_id == ParseResult.id,
                    Media.updated_at > last_sync_time,
                )
            )
            user_media_update_subquery = exists(
                select(1)
                .select_from(Media)
                .join(
                    UserMedia,
                    (UserMedia.media_id == Media.id) & (UserMedia.user_id == user_id),
                )
                .where(
                    Media.parse_result_id == ParseResult.id,
                    UserMedia.updated_at > last_sync_time,
                )
            )
            user_author_update_subquery = exists(
                select(1)
                .select_from(UserAuthor)
                .where(
                    UserAuthor.author_id == ParseResult.author_id,
                    UserAuthor.user_id == user_id,
                    UserAuthor.updated_at > last_sync_time,
                )
            )
            query = query.where(
                or_(
                    ParseResult.updated_at > last_sync_time,
                    UserParseResult.updated_at > last_sync_time,
                    media_update_subquery,
                    user_media_update_subquery,
                    user_author_update_subquery,
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = session.execute(count_query).scalar()
        total = total if total is not None else 0

        # Sort by updated_at desc (most recent first)
        query = query.order_by(ParseResult.updated_at.desc())

        query = query.limit(limit).offset(offset)
        results_orm = session.execute(query).scalars().all()

        results = []
        media_ids = [media.id for result_orm in results_orm for media in result_orm.media]
        media_tags_map = self._load_media_tags_map(user_id, media_ids)
        user_media_updated = self._load_user_media_updated_at(user_id, media_ids)
        author_ids = [result_orm.author_id for result_orm in results_orm]
        author_tags_map = self._load_author_tags_map(user_id, author_ids)
        user_author_updated = self._load_user_author_updated_at(user_id, author_ids)

        for result_orm in results_orm:
            # Check if association is deleted
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id) & (UserParseResult.parse_result_id == result_orm.id)
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()
            association_deleted_at = user_parse_result.deleted_at if user_parse_result else None

            tags = self._resolve_tags_for_ids(user_id, list(user_parse_result.tags or []) if user_parse_result else [])

            # Convert to entity and override deleted_at if needed
            entity = ParseResultEntity.from_orm(result_orm, tags=tags)
            self._apply_media_tags_to_entity(entity, media_tags_map)
            self._apply_author_tags_to_entity(entity, author_tags_map)
            entity.deleted_at = association_deleted_at or result_orm.deleted_at

            # Use the latest updated_at across parse result, user association, media, and user_media.
            # This ensures the client's next last_sync_time advances correctly when the trigger
            # was a media update (media_update_subquery), preventing infinite re-sync.
            timestamps = [result_orm.updated_at]
            if user_parse_result and user_parse_result.updated_at:
                timestamps.append(user_parse_result.updated_at)
            for media in result_orm.media:
                if media.updated_at:
                    timestamps.append(media.updated_at)
                um_updated = user_media_updated.get(media.id)
                if um_updated:
                    timestamps.append(um_updated)
            ua_updated = user_author_updated.get(result_orm.author_id)
            if ua_updated:
                timestamps.append(ua_updated)
            entity.updated_at = max(timestamps)
            results.append(entity)

        return results, total

    def list_tags(self, user_id: int) -> list[TagEntity]:
        """
        List all tags in the user's vocabulary.

        Args:
            user_id: User ID

        Returns:
            List of TagEntity ordered by name
        """
        session = self._get_session()
        stmt = select(Tag).where(Tag.user_id == user_id, Tag.deleted_at.is_(None)).order_by(Tag.name.asc())
        tags = session.execute(stmt).scalars().all()
        return [TagEntity.from_orm(tag) for tag in tags]

    def create_tag(self, user_id: int, name: str, commit: bool = True) -> TagEntity:
        """
        Create a tag in the user's vocabulary without attaching it to content.

        Args:
            user_id: User ID
            name: Tag name
            commit: Whether to commit immediately

        Returns:
            Created TagEntity

        Raises:
            ValueError: If name is empty or a tag with the same name already exists
        """
        session = self._get_session()
        normalized = normalize_tag_name(name)
        if not normalized:
            raise ValueError("Tag name cannot be empty")

        existing = session.execute(
            select(Tag).where(Tag.user_id == user_id, Tag.name == normalized)
        ).scalar_one_or_none()
        if existing:
            if existing.deleted_at is None:
                raise ValueError(f"Tag '{normalized}' already exists")
            existing.deleted_at = None
            existing.updated_at = datetime.now(UTC)
            session.flush()
            if commit:
                session.commit()
                session.refresh(existing)
            return TagEntity.from_orm(existing)

        tag = Tag(user_id=user_id, name=normalized)
        session.add(tag)
        session.flush()
        if commit:
            session.commit()
            session.refresh(tag)
        return TagEntity.from_orm(tag)

    def rename_tag(self, user_id: int, tag_id: int, name: str, commit: bool = True) -> TagEntity | None:
        """
        Rename a tag and bump updated_at on all content associations that reference it.

        Args:
            user_id: User ID
            tag_id: Tag ID
            name: New tag name
            commit: Whether to commit immediately

        Returns:
            Updated TagEntity, or None if not found

        Raises:
            ValueError: If name is empty or conflicts with another tag
        """
        session = self._get_session()
        normalized = normalize_tag_name(name)
        if not normalized:
            raise ValueError("Tag name cannot be empty")

        tag = session.execute(
            select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id, Tag.deleted_at.is_(None))
        ).scalar_one_or_none()
        if not tag:
            return None

        conflict = session.execute(
            select(Tag).where(
                Tag.user_id == user_id,
                Tag.name == normalized,
                Tag.id != tag_id,
            )
        ).scalar_one_or_none()
        if conflict:
            if conflict.deleted_at is None:
                raise ValueError(f"Tag '{normalized}' already exists")
            # Free the unique name held by a soft-deleted row
            session.delete(conflict)
            session.flush()

        tag.name = normalized
        tag.updated_at = datetime.now(UTC)
        self._bump_associations_with_tag(user_id, tag_id)
        session.flush()
        if commit:
            session.commit()
            session.refresh(tag)
        return TagEntity.from_orm(tag)

    def delete_tag(self, user_id: int, tag_id: int, commit: bool = True) -> bool:
        """
        Soft-delete a tag and remove its ID from all of the user's content tag lists.

        Args:
            user_id: User ID
            tag_id: Tag ID
            commit: Whether to commit immediately

        Returns:
            True if the tag was found and deleted
        """
        session = self._get_session()
        tag = session.execute(
            select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id, Tag.deleted_at.is_(None))
        ).scalar_one_or_none()
        if not tag:
            return False

        now = datetime.now(UTC)
        tag.deleted_at = now
        tag.updated_at = now

        associations = (
            session.execute(select(UserParseResult).where(UserParseResult.user_id == user_id)).scalars().all()
        )
        for association in associations:
            current_ids = list(association.tags or [])
            if tag_id not in current_ids:
                continue
            association.tags = [tid for tid in current_ids if tid != tag_id]
            flag_modified(association, "tags")
            association.updated_at = now

        user_media_rows = session.execute(select(UserMedia).where(UserMedia.user_id == user_id)).scalars().all()
        for user_media in user_media_rows:
            current_ids = list(user_media.tags or [])
            if tag_id not in current_ids:
                continue
            user_media.tags = [tid for tid in current_ids if tid != tag_id]
            flag_modified(user_media, "tags")
            user_media.updated_at = now

        user_author_rows = session.execute(select(UserAuthor).where(UserAuthor.user_id == user_id)).scalars().all()
        for user_author in user_author_rows:
            current_ids = list(user_author.tags or [])
            if tag_id not in current_ids:
                continue
            user_author.tags = [tid for tid in current_ids if tid != tag_id]
            flag_modified(user_author, "tags")
            user_author.updated_at = now

        session.flush()
        if commit:
            session.commit()
        return True

    def apply_tag_assignment(
        self,
        user_id: int,
        target: str,
        target_id: int,
        mode: str,
        names: list[str] | None = None,
        tag_ids: list[int] | None = None,
        commit: bool = True,
    ) -> list[TagEntity] | None:
        """
        Apply a tag assignment to content, media, or author.

        Args:
            user_id: User ID
            target: One of content, media, author
            target_id: parse_result_id, media_id, or author_id
            mode: replace, add, or remove
            names: Tag names for replace/add/remove
            tag_ids: Tag IDs for remove
            commit: Whether to commit immediately

        Returns:
            Resulting TagEntity list, or None if the target is not accessible
        """
        if mode == "remove":
            if target == "content":
                return self.remove_content_tags(user_id, target_id, names=names, tag_ids=tag_ids, commit=commit)
            if target == "media":
                return self.remove_media_tags(user_id, target_id, names=names, tag_ids=tag_ids, commit=commit)
            if target == "author":
                return self.remove_author_tags(user_id, target_id, names=names, tag_ids=tag_ids, commit=commit)
            raise ValueError(f"Unsupported tag assignment target: {target}")

        resolved_names = names or []
        if target == "content":
            if mode == "replace":
                return self.replace_content_tags(user_id, target_id, resolved_names, commit=commit)
            if mode == "add":
                return self.add_content_tags(user_id, target_id, resolved_names, commit=commit)
        elif target == "media":
            if mode == "replace":
                return self.replace_media_tags(user_id, target_id, resolved_names, commit=commit)
            if mode == "add":
                return self.add_media_tags(user_id, target_id, resolved_names, commit=commit)
        elif target == "author":
            if mode == "replace":
                return self.replace_author_tags(user_id, target_id, resolved_names, commit=commit)
            if mode == "add":
                return self.add_author_tags(user_id, target_id, resolved_names, commit=commit)
        else:
            raise ValueError(f"Unsupported tag assignment target: {target}")

        raise ValueError(f"Unsupported tag assignment mode: {mode}")

    def replace_content_tags(
        self, user_id: int, parse_result_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Fully replace tags on a content item. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            parse_result_id: Parse result ID
            names: Tag names (empty list clears all tags)
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list, or None if content association not found
        """
        return self._mutate_content_tags(
            user_id=user_id,
            parse_result_id=parse_result_id,
            names=names,
            mode="replace",
            commit=commit,
        )

    def add_content_tags(
        self, user_id: int, parse_result_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Incrementally add tags to a content item. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            parse_result_id: Parse result ID
            names: Tag names to add
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if content association not found
        """
        return self._mutate_content_tags(
            user_id=user_id,
            parse_result_id=parse_result_id,
            names=names,
            mode="add",
            commit=commit,
        )

    def remove_content_tags(
        self,
        user_id: int,
        parse_result_id: int,
        names: list[str] | None = None,
        tag_ids: list[int] | None = None,
        commit: bool = True,
    ) -> list[TagEntity] | None:
        """
        Incrementally remove tags from a content item by name and/or id.

        Args:
            user_id: User ID
            parse_result_id: Parse result ID
            names: Tag names to remove
            tag_ids: Tag IDs to remove
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if content association not found
        """
        session = self._get_session()
        association = self._get_active_user_parse_result(user_id, parse_result_id)
        if not association:
            return None

        remove_ids: set[int] = set(tag_ids or [])
        normalized_names = normalize_tag_names(names or [])
        if normalized_names:
            stmt = select(Tag).where(
                Tag.user_id == user_id,
                Tag.name.in_(normalized_names),
                Tag.deleted_at.is_(None),
            )
            for tag in session.execute(stmt).scalars().all():
                remove_ids.add(tag.id)

        current_ids = list(association.tags or [])
        new_ids = [tid for tid in current_ids if tid not in remove_ids]
        if new_ids != current_ids:
            association.tags = new_ids
            flag_modified(association, "tags")
            association.updated_at = datetime.now(UTC)
            session.flush()
            if commit:
                session.commit()

        return self._resolve_tags_for_ids(user_id, new_ids)

    def replace_media_tags(
        self, user_id: int, media_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Fully replace tags on a media item. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            media_id: Media ID
            names: Tag names (empty list clears all tags)
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list, or None if media is not accessible
        """
        return self._mutate_media_tags(user_id=user_id, media_id=media_id, names=names, mode="replace", commit=commit)

    def add_media_tags(
        self, user_id: int, media_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Incrementally add tags to a media item. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            media_id: Media ID
            names: Tag names to add
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if media is not accessible
        """
        return self._mutate_media_tags(user_id=user_id, media_id=media_id, names=names, mode="add", commit=commit)

    def remove_media_tags(
        self,
        user_id: int,
        media_id: int,
        names: list[str] | None = None,
        tag_ids: list[int] | None = None,
        commit: bool = True,
    ) -> list[TagEntity] | None:
        """
        Incrementally remove tags from a media item by name and/or id.

        Args:
            user_id: User ID
            media_id: Media ID
            names: Tag names to remove
            tag_ids: Tag IDs to remove
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if media is not accessible
        """
        session = self._get_session()
        user_media = self._get_or_create_user_media(user_id, media_id, create=False)
        if user_media is None and not self._user_can_access_media(user_id, media_id):
            return None
        if user_media is None:
            # Accessible media with no tags row yet — nothing to remove
            return []

        remove_ids: set[int] = set(tag_ids or [])
        normalized_names = normalize_tag_names(names or [])
        if normalized_names:
            stmt = select(Tag).where(
                Tag.user_id == user_id,
                Tag.name.in_(normalized_names),
                Tag.deleted_at.is_(None),
            )
            for tag in session.execute(stmt).scalars().all():
                remove_ids.add(tag.id)

        current_ids = list(user_media.tags or [])
        new_ids = [tid for tid in current_ids if tid not in remove_ids]
        if new_ids != current_ids:
            user_media.tags = new_ids
            flag_modified(user_media, "tags")
            user_media.updated_at = datetime.now(UTC)
            session.flush()
            if commit:
                session.commit()

        return self._resolve_tags_for_ids(user_id, new_ids)

    def replace_author_tags(
        self, user_id: int, author_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Fully replace tags on an author. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            author_id: Author ID
            names: Tag names (empty list clears all tags)
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list, or None if author is not accessible
        """
        return self._mutate_author_tags(
            user_id=user_id, author_id=author_id, names=names, mode="replace", commit=commit
        )

    def add_author_tags(
        self, user_id: int, author_id: int, names: list[str], commit: bool = True
    ) -> list[TagEntity] | None:
        """
        Incrementally add tags to an author. Names are upserted into the vocabulary.

        Args:
            user_id: User ID
            author_id: Author ID
            names: Tag names to add
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if author is not accessible
        """
        return self._mutate_author_tags(user_id=user_id, author_id=author_id, names=names, mode="add", commit=commit)

    def remove_author_tags(
        self,
        user_id: int,
        author_id: int,
        names: list[str] | None = None,
        tag_ids: list[int] | None = None,
        commit: bool = True,
    ) -> list[TagEntity] | None:
        """
        Incrementally remove tags from an author by name and/or id.

        Args:
            user_id: User ID
            author_id: Author ID
            names: Tag names to remove
            tag_ids: Tag IDs to remove
            commit: Whether to commit immediately

        Returns:
            Resolved TagEntity list after update, or None if author is not accessible
        """
        session = self._get_session()
        association = self._get_active_user_author(user_id, author_id)
        if not association:
            return None

        remove_ids: set[int] = set(tag_ids or [])
        normalized_names = normalize_tag_names(names or [])
        if normalized_names:
            stmt = select(Tag).where(
                Tag.user_id == user_id,
                Tag.name.in_(normalized_names),
                Tag.deleted_at.is_(None),
            )
            for tag in session.execute(stmt).scalars().all():
                remove_ids.add(tag.id)

        current_ids = list(association.tags or [])
        new_ids = [tid for tid in current_ids if tid not in remove_ids]
        if new_ids != current_ids:
            association.tags = new_ids
            flag_modified(association, "tags")
            association.updated_at = datetime.now(UTC)
            session.flush()
            if commit:
                session.commit()

        return self._resolve_tags_for_ids(user_id, new_ids)

    def get_or_create_tags_by_names(self, user_id: int, names: list[str], commit: bool = False) -> list[TagEntity]:
        """
        Resolve tag names to Tag entities, creating missing ones.

        Args:
            user_id: User ID
            names: Tag names
            commit: Whether to commit immediately

        Returns:
            TagEntity list in the same order as normalized unique names
        """
        session = self._get_session()
        normalized = normalize_tag_names(names)
        if not normalized:
            return []

        existing = session.execute(select(Tag).where(Tag.user_id == user_id, Tag.name.in_(normalized))).scalars().all()
        by_name = {tag.name: tag for tag in existing}

        changed = False
        for name in normalized:
            tag = by_name.get(name)
            if tag is not None:
                if tag.deleted_at is not None:
                    tag.deleted_at = None
                    tag.updated_at = datetime.now(UTC)
                    changed = True
                continue
            tag = Tag(user_id=user_id, name=name)
            session.add(tag)
            session.flush()
            by_name[name] = tag
            changed = True

        if commit and changed:
            session.commit()
            for tag in by_name.values():
                session.refresh(tag)
        elif changed:
            session.flush()

        return [TagEntity.from_orm(by_name[name]) for name in normalized]

    def _mutate_content_tags(
        self,
        user_id: int,
        parse_result_id: int,
        names: list[str],
        mode: str,
        commit: bool,
    ) -> list[TagEntity] | None:
        """Replace or add content tags by name (upsert vocabulary)."""
        session = self._get_session()
        association = self._get_active_user_parse_result(user_id, parse_result_id)
        if not association:
            return None

        tag_entities = self.get_or_create_tags_by_names(user_id, names, commit=False)
        new_ids = [tag.id for tag in tag_entities if tag.id is not None]
        current_ids = list(association.tags or [])

        if mode == "replace":
            target_ids = new_ids
        else:
            seen = set(current_ids)
            target_ids = list(current_ids)
            for tag_id in new_ids:
                if tag_id not in seen:
                    target_ids.append(tag_id)
                    seen.add(tag_id)

        if target_ids != current_ids:
            association.tags = target_ids
            flag_modified(association, "tags")
            association.updated_at = datetime.now(UTC)

        session.flush()
        if commit:
            session.commit()

        return self._resolve_tags_for_ids(user_id, list(association.tags or []))

    def _mutate_media_tags(
        self,
        user_id: int,
        media_id: int,
        names: list[str],
        mode: str,
        commit: bool,
    ) -> list[TagEntity] | None:
        """Replace or add media tags by name (upsert vocabulary)."""
        session = self._get_session()
        if not self._user_can_access_media(user_id, media_id):
            return None

        user_media = self._get_or_create_user_media(user_id, media_id, create=True)
        if user_media is None:
            return None

        tag_entities = self.get_or_create_tags_by_names(user_id, names, commit=False)
        new_ids = [tag.id for tag in tag_entities if tag.id is not None]
        current_ids = list(user_media.tags or [])

        if mode == "replace":
            target_ids = new_ids
        else:
            seen = set(current_ids)
            target_ids = list(current_ids)
            for tag_id in new_ids:
                if tag_id not in seen:
                    target_ids.append(tag_id)
                    seen.add(tag_id)

        if target_ids != current_ids:
            user_media.tags = target_ids
            flag_modified(user_media, "tags")
            user_media.updated_at = datetime.now(UTC)

        session.flush()
        if commit:
            session.commit()

        return self._resolve_tags_for_ids(user_id, list(user_media.tags or []))

    def _mutate_author_tags(
        self,
        user_id: int,
        author_id: int,
        names: list[str],
        mode: str,
        commit: bool,
    ) -> list[TagEntity] | None:
        """Replace or add author tags by name (upsert vocabulary)."""
        session = self._get_session()
        association = self._get_active_user_author(user_id, author_id)
        if not association:
            return None

        tag_entities = self.get_or_create_tags_by_names(user_id, names, commit=False)
        new_ids = [tag.id for tag in tag_entities if tag.id is not None]
        current_ids = list(association.tags or [])

        if mode == "replace":
            target_ids = new_ids
        else:
            seen = set(current_ids)
            target_ids = list(current_ids)
            for tag_id in new_ids:
                if tag_id not in seen:
                    target_ids.append(tag_id)
                    seen.add(tag_id)

        if target_ids != current_ids:
            association.tags = target_ids
            flag_modified(association, "tags")
            association.updated_at = datetime.now(UTC)

        session.flush()
        if commit:
            session.commit()

        return self._resolve_tags_for_ids(user_id, list(association.tags or []))

    def _user_can_access_media(self, user_id: int, media_id: int) -> bool:
        """Return True if the user has an active association to the media's parse result."""
        session = self._get_session()
        stmt = (
            select(Media.id)
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == Media.parse_result_id)
                & (UserParseResult.user_id == user_id)
                & (UserParseResult.deleted_at.is_(None)),
            )
            .where(Media.id == media_id, Media.deleted_at.is_(None))
        )
        return session.execute(stmt).scalar_one_or_none() is not None

    def _get_or_create_user_media(self, user_id: int, media_id: int, create: bool) -> UserMedia | None:
        """Get UserMedia row, optionally creating/reviving it when the user can access the media."""
        session = self._get_session()
        user_media = session.execute(
            select(UserMedia).where(UserMedia.user_id == user_id, UserMedia.media_id == media_id)
        ).scalar_one_or_none()
        if user_media is not None:
            if user_media.deleted_at is not None:
                # Only revive soft-deleted rows when create=True (replace/add).
                # create=False callers (e.g. remove) must not resurrect old tags.
                if not create:
                    return None
                user_media.deleted_at = None
                user_media.updated_at = datetime.now(UTC)
            return user_media
        if not create:
            return None
        if not self._user_can_access_media(user_id, media_id):
            return None
        user_media = UserMedia(user_id=user_id, media_id=media_id, tags=[])
        session.add(user_media)
        session.flush()
        return user_media

    def _get_active_user_parse_result(self, user_id: int, parse_result_id: int) -> UserParseResult | None:
        """Get a non-deleted user-content association."""
        session = self._get_session()
        return session.execute(
            select(UserParseResult).where(
                UserParseResult.user_id == user_id,
                UserParseResult.parse_result_id == parse_result_id,
                UserParseResult.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    def _get_active_user_author(self, user_id: int, author_id: int) -> UserAuthor | None:
        """Get a non-deleted user-author association."""
        session = self._get_session()
        return session.execute(
            select(UserAuthor).where(
                UserAuthor.user_id == user_id,
                UserAuthor.author_id == author_id,
                UserAuthor.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    def _bump_associations_with_tag(self, user_id: int, tag_id: int) -> None:
        """Bump updated_at on associations that reference the given tag id."""
        session = self._get_session()
        now = datetime.now(UTC)
        associations = (
            session.execute(select(UserParseResult).where(UserParseResult.user_id == user_id)).scalars().all()
        )
        for association in associations:
            if tag_id in list(association.tags or []):
                association.updated_at = now

        user_media_rows = session.execute(select(UserMedia).where(UserMedia.user_id == user_id)).scalars().all()
        for user_media in user_media_rows:
            if tag_id in list(user_media.tags or []):
                user_media.updated_at = now

        user_author_rows = session.execute(select(UserAuthor).where(UserAuthor.user_id == user_id)).scalars().all()
        for user_author in user_author_rows:
            if tag_id in list(user_author.tags or []):
                user_author.updated_at = now

    def _resolve_tags_for_ids(self, user_id: int, tag_ids: list[int]) -> list[TagEntity]:
        """
        Resolve tag IDs to TagEntity, dropping missing/deleted IDs while preserving order.
        """
        if not tag_ids:
            return []

        session = self._get_session()
        unique_ids = list(dict.fromkeys(int(tid) for tid in tag_ids))
        tags = (
            session.execute(
                select(Tag).where(
                    Tag.user_id == user_id,
                    Tag.id.in_(unique_ids),
                    Tag.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        by_id = {tag.id: TagEntity.from_orm(tag) for tag in tags}
        return [by_id[tid] for tid in unique_ids if tid in by_id]

    def _load_media_tags_map(self, user_id: int, media_ids: list[int]) -> dict[int, list[TagEntity]]:
        """Load resolved per-user tags keyed by media id."""
        if not media_ids:
            return {}

        session = self._get_session()
        unique_media_ids = list(dict.fromkeys(media_ids))
        rows = (
            session.execute(
                select(UserMedia).where(
                    UserMedia.user_id == user_id,
                    UserMedia.media_id.in_(unique_media_ids),
                    UserMedia.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        all_tag_ids: list[int] = []
        raw_by_media: dict[int, list[int]] = {}
        for row in rows:
            ids = list(row.tags or [])
            raw_by_media[row.media_id] = ids
            all_tag_ids.extend(ids)

        resolved = {tag.id: tag for tag in self._resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}
        return {
            media_id: [resolved[tid] for tid in dict.fromkeys(ids) if tid in resolved]
            for media_id, ids in raw_by_media.items()
        }

    def _load_user_media_updated_at(self, user_id: int, media_ids: list[int]) -> dict[int, datetime]:
        """Load UserMedia.updated_at keyed by media id."""
        if not media_ids:
            return {}
        session = self._get_session()
        unique_media_ids = list(dict.fromkeys(media_ids))
        rows = (
            session.execute(
                select(UserMedia).where(
                    UserMedia.user_id == user_id,
                    UserMedia.media_id.in_(unique_media_ids),
                )
            )
            .scalars()
            .all()
        )
        return {row.media_id: row.updated_at for row in rows if row.updated_at is not None}

    def _load_author_tags_map(self, user_id: int, author_ids: list[int]) -> dict[int, list[TagEntity]]:
        """Load resolved per-user tags keyed by author id."""
        if not author_ids:
            return {}

        session = self._get_session()
        unique_author_ids = list(dict.fromkeys(author_ids))
        rows = (
            session.execute(
                select(UserAuthor).where(
                    UserAuthor.user_id == user_id,
                    UserAuthor.author_id.in_(unique_author_ids),
                    UserAuthor.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )
        all_tag_ids: list[int] = []
        raw_by_author: dict[int, list[int]] = {}
        for row in rows:
            ids = list(row.tags or [])
            raw_by_author[row.author_id] = ids
            all_tag_ids.extend(ids)

        resolved = {tag.id: tag for tag in self._resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}
        return {
            author_id: [resolved[tid] for tid in dict.fromkeys(ids) if tid in resolved]
            for author_id, ids in raw_by_author.items()
        }

    def _load_user_author_updated_at(self, user_id: int, author_ids: list[int]) -> dict[int, datetime]:
        """Load UserAuthor.updated_at keyed by author id."""
        if not author_ids:
            return {}
        session = self._get_session()
        unique_author_ids = list(dict.fromkeys(author_ids))
        rows = (
            session.execute(
                select(UserAuthor).where(
                    UserAuthor.user_id == user_id,
                    UserAuthor.author_id.in_(unique_author_ids),
                )
            )
            .scalars()
            .all()
        )
        return {row.author_id: row.updated_at for row in rows if row.updated_at is not None}

    @staticmethod
    def _apply_media_tags_to_entity(entity: ParseResultEntity, media_tags_map: dict[int, list[TagEntity]]) -> None:
        """Attach resolved media tags onto a parse result entity in place."""
        for media in entity.media:
            if media.id is None:
                continue
            media.tags = media_tags_map.get(media.id, [])

    @staticmethod
    def _apply_author_tags_to_entity(entity: ParseResultEntity, author_tags_map: dict[int, list[TagEntity]]) -> None:
        """Attach resolved author tags onto a parse result entity in place."""
        if entity.author.id is None:
            return
        entity.author.tags = author_tags_map.get(entity.author.id, [])

    def _entities_with_user_tags(self, user_id: int, results_orm: list[ParseResult]) -> list[ParseResultEntity]:
        """Attach resolved per-user content, media, and author tags to parse result entities."""
        if not results_orm:
            return []

        session = self._get_session()
        result_ids = [result.id for result in results_orm]
        associations = (
            session.execute(
                select(UserParseResult).where(
                    UserParseResult.user_id == user_id,
                    UserParseResult.parse_result_id.in_(result_ids),
                )
            )
            .scalars()
            .all()
        )
        tags_by_result = {association.parse_result_id: list(association.tags or []) for association in associations}

        all_tag_ids: list[int] = []
        for ids in tags_by_result.values():
            all_tag_ids.extend(ids)
        resolved = {tag.id: tag for tag in self._resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}

        media_ids = [media.id for result in results_orm for media in result.media]
        media_tags_map = self._load_media_tags_map(user_id, media_ids)
        author_ids = [result.author_id for result in results_orm]
        author_tags_map = self._load_author_tags_map(user_id, author_ids)

        entities: list[ParseResultEntity] = []
        for result_orm in results_orm:
            tag_ids = tags_by_result.get(result_orm.id, [])
            tags = [resolved[tid] for tid in dict.fromkeys(tag_ids) if tid in resolved]
            entity = ParseResultEntity.from_orm(result_orm, tags=tags)
            self._apply_media_tags_to_entity(entity, media_tags_map)
            self._apply_author_tags_to_entity(entity, author_tags_map)
            entities.append(entity)
        return entities

    @staticmethod
    def _apply_tag_filters(query, tag_id: int | None = None, exclude_tag_id: int | None = None):
        """
        Apply include/exclude tag filters.

        Matches content-level, media-level, or author-level tags for the same user.
        """
        if tag_id is not None:
            content_tag_values = (
                func.json_each(UserParseResult.tags).table_valued("value").alias("include_content_tags")
            )
            content_has_tag = exists(
                select(1).select_from(content_tag_values).where(cast(content_tag_values.c.value, Integer) == tag_id)
            )
            media_tag_values = func.json_each(UserMedia.tags).table_valued("value").alias("include_media_tags")
            media_has_tag = exists(
                select(1)
                .select_from(Media)
                .join(
                    UserMedia,
                    (UserMedia.media_id == Media.id)
                    & (UserMedia.user_id == UserParseResult.user_id)
                    & (UserMedia.deleted_at.is_(None)),
                )
                .join(media_tag_values, cast(media_tag_values.c.value, Integer) == tag_id)
                .where(
                    Media.parse_result_id == ParseResult.id,
                    Media.deleted_at.is_(None),
                )
            )
            author_tag_values = func.json_each(UserAuthor.tags).table_valued("value").alias("include_author_tags")
            author_has_tag = exists(
                select(1)
                .select_from(UserAuthor)
                .join(author_tag_values, cast(author_tag_values.c.value, Integer) == tag_id)
                .where(
                    UserAuthor.author_id == ParseResult.author_id,
                    UserAuthor.user_id == UserParseResult.user_id,
                    UserAuthor.deleted_at.is_(None),
                )
            )
            query = query.where(or_(content_has_tag, media_has_tag, author_has_tag))

        if exclude_tag_id is not None:
            content_tag_values = (
                func.json_each(UserParseResult.tags).table_valued("value").alias("exclude_content_tags")
            )
            content_has_tag = exists(
                select(1)
                .select_from(content_tag_values)
                .where(cast(content_tag_values.c.value, Integer) == exclude_tag_id)
            )
            media_tag_values = func.json_each(UserMedia.tags).table_valued("value").alias("exclude_media_tags")
            media_has_tag = exists(
                select(1)
                .select_from(Media)
                .join(
                    UserMedia,
                    (UserMedia.media_id == Media.id)
                    & (UserMedia.user_id == UserParseResult.user_id)
                    & (UserMedia.deleted_at.is_(None)),
                )
                .join(media_tag_values, cast(media_tag_values.c.value, Integer) == exclude_tag_id)
                .where(
                    Media.parse_result_id == ParseResult.id,
                    Media.deleted_at.is_(None),
                )
            )
            author_tag_values = func.json_each(UserAuthor.tags).table_valued("value").alias("exclude_author_tags")
            author_has_tag = exists(
                select(1)
                .select_from(UserAuthor)
                .join(author_tag_values, cast(author_tag_values.c.value, Integer) == exclude_tag_id)
                .where(
                    UserAuthor.author_id == ParseResult.author_id,
                    UserAuthor.user_id == UserParseResult.user_id,
                    UserAuthor.deleted_at.is_(None),
                )
            )
            query = query.where(~or_(content_has_tag, media_has_tag, author_has_tag))

        return query

    @staticmethod
    def _apply_author_list_tag_filters(query, tag_id: int | None = None, exclude_tag_id: int | None = None):
        """Apply include/exclude tag filters for author list queries."""
        if tag_id is not None:
            author_tag_values = func.json_each(UserAuthor.tags).table_valued("value").alias("list_include_author_tags")
            query = query.where(
                exists(
                    select(1).select_from(author_tag_values).where(cast(author_tag_values.c.value, Integer) == tag_id)
                )
            )
        if exclude_tag_id is not None:
            author_tag_values = func.json_each(UserAuthor.tags).table_valued("value").alias("list_exclude_author_tags")
            query = query.where(
                ~exists(
                    select(1)
                    .select_from(author_tag_values)
                    .where(cast(author_tag_values.c.value, Integer) == exclude_tag_id)
                )
            )
        return query

    def list_platforms(
        self,
        user_id: int,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "id",
        order: str = "asc",
    ) -> tuple[list[PlatformEntity], int]:
        """
        List all platforms associated with the user, with pagination and sorting.

        Args:
            user_id: Filter by user ID
            limit: Maximum number of results to return
            offset: Number of results to skip
            sort_by: Field to sort by (id, name, created_at, updated_at)
            order: Sort order (asc, desc)

        Returns tuple of (list of PlatformEntity objects, total count).
        """
        session = self._get_session()

        # Build query with JOIN to UserPlatform
        query = (
            select(Platform)
            .join(
                UserPlatform,
                (UserPlatform.platform_id == Platform.id)
                & (UserPlatform.user_id == user_id)
                & (UserPlatform.deleted_at.is_(None)),
            )
            .where(Platform.deleted_at.is_(None))
        )

        # Get total count
        count_query = (
            select(func.count(Platform.id))
            .join(
                UserPlatform,
                (UserPlatform.platform_id == Platform.id)
                & (UserPlatform.user_id == user_id)
                & (UserPlatform.deleted_at.is_(None)),
            )
            .where(Platform.deleted_at.is_(None))
        )
        total = session.execute(count_query).scalar() or 0

        # Add sorting
        sort_field_map = {
            "name": Platform.name,
            "created_at": Platform.created_at,
            "updated_at": Platform.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Platform.id)

        query = query.order_by(sort_field.asc()) if order.lower() == "asc" else query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        platforms_orm = session.execute(query).scalars().all()

        platforms = [PlatformEntity.from_orm(p) for p in platforms_orm]
        return platforms, total

    def list_authors(
        self,
        user_id: int,
        platform_id: int | None = None,
        tag_id: int | None = None,
        exclude_tag_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "id",
        order: str = "asc",
    ) -> tuple[list[AuthorEntity], int]:
        """
        List authors associated with the user, with pagination and sorting, optionally filtered by platform_id.

        Args:
            user_id: Filter by user ID
            platform_id: Optional filter by platform ID
            tag_id: Only include authors with this tag ID
            exclude_tag_id: Exclude authors with this tag ID
            limit: Maximum number of results to return
            offset: Number of results to skip
            sort_by: Field to sort by (id, name, created_at, updated_at)
            order: Sort order (asc, desc)

        Returns tuple of (list of AuthorEntity objects with platform information, total count).
        """
        session = self._get_session()

        # Build query with JOIN to UserAuthor
        query = (
            select(Author)
            .join(
                UserAuthor,
                (UserAuthor.author_id == Author.id)
                & (UserAuthor.user_id == user_id)
                & (UserAuthor.deleted_at.is_(None)),
            )
            .where(Author.deleted_at.is_(None))
        )

        if platform_id is not None:
            query = query.where(Author.platform_id == platform_id)

        query = self._apply_author_list_tag_filters(query, tag_id=tag_id, exclude_tag_id=exclude_tag_id)

        # Get total count
        count_query = (
            select(func.count(Author.id))
            .join(
                UserAuthor,
                (UserAuthor.author_id == Author.id)
                & (UserAuthor.user_id == user_id)
                & (UserAuthor.deleted_at.is_(None)),
            )
            .where(Author.deleted_at.is_(None))
        )
        if platform_id is not None:
            count_query = count_query.where(Author.platform_id == platform_id)
        count_query = self._apply_author_list_tag_filters(count_query, tag_id=tag_id, exclude_tag_id=exclude_tag_id)
        total = session.execute(count_query).scalar() or 0

        # Add sorting
        sort_field_map = {
            "name": Author.name,
            "created_at": Author.created_at,
            "updated_at": Author.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Author.id)

        query = query.order_by(sort_field.asc()) if order.lower() == "asc" else query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        authors_orm = session.execute(query).scalars().all()

        author_ids = [author.id for author in authors_orm]
        author_tags_map = self._load_author_tags_map(user_id, author_ids)
        authors = [AuthorEntity.from_orm(author, tags=author_tags_map.get(author.id, [])) for author in authors_orm]
        return authors, total

    def delete_platform(
        self, user_id: int, platform_id: int, commit: bool = False
    ) -> tuple[bool, list[ContentDirectory]]:
        """
        Soft delete user's association with platform and cascade to related authors and parse results.
        Does NOT delete the platform itself as it's shared among users.

        Args:
            user_id: User ID performing the deletion
            platform_id: Platform ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of content directories to delete)
        """
        session = self._get_session()
        all_content_dirs: list[ContentDirectory] = []

        try:
            # Verify user-platform association exists
            stmt = select(UserPlatform).where(
                (UserPlatform.user_id == user_id)
                & (UserPlatform.platform_id == platform_id)
                & (UserPlatform.deleted_at.is_(None))
            )
            user_platform = session.execute(stmt).scalar_one_or_none()

            if not user_platform:
                logger.warning(f"Platform {platform_id} not found or already deleted for user {user_id}")
                return False, all_content_dirs

            # Get all authors belonging to this platform for this user
            stmt = (
                select(Author.id)
                .join(
                    UserAuthor,
                    (UserAuthor.author_id == Author.id)
                    & (UserAuthor.user_id == user_id)
                    & (UserAuthor.deleted_at.is_(None)),
                )
                .where((Author.platform_id == platform_id) & (Author.deleted_at.is_(None)))
            )
            author_ids = session.execute(stmt).scalars().all()

            logger.debug(f"Soft deleting user {user_id}'s platform {platform_id} with {len(author_ids)} authors")

            # Soft delete each author association
            for author_id in author_ids:
                _success, content_dirs = self.delete_author(user_id, author_id, commit=False)
                all_content_dirs.extend(content_dirs)

            # Soft delete user-platform association
            user_platform.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, all_content_dirs

        except Exception as e:
            if commit:
                session.rollback()
            logger.exception(f"Database error when soft deleting platform {platform_id} for user {user_id}")
            raise Exception(f"Failed to soft delete platform association: {e}") from e

    def delete_author(self, user_id: int, author_id: int, commit: bool = False) -> tuple[bool, list[ContentDirectory]]:
        """
        Soft delete user's association with author and cascade to related parse results.
        Does NOT delete the author itself as it's shared among users.

        Args:
            user_id: User ID performing the deletion
            author_id: Author ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of content directories to delete)
        """
        session = self._get_session()
        all_content_dirs: list[ContentDirectory] = []

        try:
            # Verify user-author association exists
            stmt = select(UserAuthor).where(
                (UserAuthor.user_id == user_id)
                & (UserAuthor.author_id == author_id)
                & (UserAuthor.deleted_at.is_(None))
            )
            user_author = session.execute(stmt).scalar_one_or_none()

            if not user_author:
                logger.warning(f"Author {author_id} not found or already deleted for user {user_id}")
                return False, all_content_dirs

            # Get all parse result IDs for this author for this user
            stmt = (
                select(ParseResult.id)
                .join(
                    UserParseResult,
                    (UserParseResult.parse_result_id == ParseResult.id)
                    & (UserParseResult.user_id == user_id)
                    & (UserParseResult.deleted_at.is_(None)),
                )
                .where((ParseResult.author_id == author_id) & (ParseResult.deleted_at.is_(None)))
            )
            parse_result_ids = session.execute(stmt).scalars().all()

            logger.debug(
                f"Soft deleting user {user_id}'s author {author_id} with {len(parse_result_ids)} parse results"
            )

            # Soft delete each parse result association
            for pr_id in parse_result_ids:
                _success, content_dirs = self.delete_parse_result(user_id, pr_id, commit=False)
                all_content_dirs.extend(content_dirs)

            # Soft delete user-author association
            user_author.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, all_content_dirs

        except Exception as e:
            if commit:
                session.rollback()
            logger.exception(f"Database error when soft deleting author {author_id} for user {user_id}")
            raise Exception(f"Failed to soft delete author association: {e}") from e

    def delete_parse_result(
        self, user_id: int, parse_result_id: int, commit: bool = False
    ) -> tuple[bool, list[ContentDirectory]]:
        """
        Soft delete user's association with parse result.
        The parse result itself is shared among users, so it is only soft-deleted
        (and its media hard-deleted) once no other active user association remains.
        Only deletes on-disk content directories if they become completely orphaned.

        Args:
            user_id: User ID performing the deletion
            parse_result_id: Parse result ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of content directories to delete)
        """
        session = self._get_session()
        content_dirs: list[ContentDirectory] = []

        try:
            # Verify user-parse_result association exists
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id)
                & (UserParseResult.parse_result_id == parse_result_id)
                & (UserParseResult.deleted_at.is_(None))
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()

            if not user_parse_result:
                logger.warning(f"Parse result {parse_result_id} not found or already deleted for user {user_id}")
                raise ValueError(f"Parse result {parse_result_id} not found or already deleted")

            # Get parse result (platform/author needed to resolve the content directory)
            result_orm = (
                session.query(ParseResult)
                .options(
                    selectinload(ParseResult.platform),
                    selectinload(ParseResult.author),
                )
                .filter(ParseResult.id == parse_result_id)
                .first()
            )

            if not result_orm:
                raise ValueError(f"Parse result {parse_result_id} not found")

            # Check if parse result becomes completely orphaned (no other active user associations)
            stmt = select(func.count(UserParseResult.user_id)).where(
                (UserParseResult.parse_result_id == parse_result_id)
                & (UserParseResult.deleted_at.is_(None))
                & (UserParseResult.user_id != user_id)
            )
            other_users_count = session.execute(stmt).scalar()

            # If parse result becomes orphaned, collect content directory and clean up
            if other_users_count == 0:
                logger.debug(f"Parse result {parse_result_id} will be orphaned, scheduling content directory deletion")

                if result_orm.platform is None or result_orm.author is None:
                    raise ValueError(f"Parse result {parse_result_id} is missing platform or author")

                content_dirs.append(
                    ContentDirectory(
                        platform_code=result_orm.platform.code,
                        author_uid=result_orm.author.uid,
                        content_id=resolve_content_id(result_orm.pid, result_orm.url),
                    )
                )

                # Media is owned by this parse result (one-to-many); hard delete its rows.
                deleted_media = session.query(Media).filter(Media.parse_result_id == parse_result_id).delete()
                if deleted_media:
                    logger.debug(f"Hard deleted {deleted_media} media records for parse result {parse_result_id}")

                # Also soft delete the parse result itself if it's orphaned
                result_orm.deleted_at = datetime.now(UTC)

            # Soft delete user-parse_result association
            user_parse_result.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, content_dirs

        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Unexpected error when soft deleting parse result {parse_result_id} for user {user_id}")
            raise
