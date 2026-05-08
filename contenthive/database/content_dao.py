from datetime import UTC, datetime

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import (
    Author,
    Media,
    ParseResult,
    ParseResultMedia,
    Platform,
    UserAuthor,
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
)
from contenthive.models.enumerates import MediaStatus
from contenthive.plugins.contracts import (
    ParserAuthorInfo,
    ParserMediaInfo,
    ParserPlatformInfo,
    ParserResult,
)


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

    def save_platform(
        self, platform: ParserPlatformInfo, user_id: int, commit: bool = False
    ) -> int:
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
                existing_platform.icon_url = (
                    str(platform.icon_url) if platform.icon_url else None
                )
                # Restore if soft-deleted
                if existing_platform.deleted_at is not None:
                    existing_platform.deleted_at = None
                    logger.info(
                        f"Restored soft-deleted platform {existing_platform.id}"
                    )
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
                (UserPlatform.user_id == user_id)
                & (UserPlatform.platform_id == platform_id)
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
            raise Exception(f"Failed to save platform: {e}")

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
            stmt = select(Author).where(
                (Author.platform_id == platform_id) & (Author.uid == author.uid)
            )
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
            stmt = select(UserAuthor).where(
                (UserAuthor.user_id == user_id) & (UserAuthor.author_id == author_id)
            )
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
            raise Exception(f"Failed to save author: {e}")

    def _save_media(self, media: MediaEntity, commit: bool = False) -> int:
        """
        Save media information.

        Args:
            media: Media entity
            commit: Whether to commit immediately (default: False)

        Returns media_id.
        """
        session = self._get_session()
        try:
            # Check if media exists
            stmt = select(Media).where(Media.url == media.url)
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
            raise Exception(f"Failed to save media: {e}")

    def save_medias(
        self, medias: list[ParserMediaInfo], commit: bool = False
    ) -> list[int]:
        """
        Save multiple media entities.

        Args:
            medias: List of ParserMediaInfo objects
            commit: Whether to commit immediately (default: False)

        Returns list of media_ids.
        """
        media_ids = []
        for media in medias:
            media_entity = MediaEntity(
                status=MediaStatus.PENDING,  # Default to pending when saving from parser result
                url=str(media.url),
                type=media.type if media.type else None,
                title=media.title,
                cover=str(media.cover) if media.cover else None,
                url_fallbacks=[str(u) for u in (media.url_fallbacks or [])],
                cover_fallbacks=[str(u) for u in (media.cover_fallbacks or [])],
            )
            media_id = self._save_media(media_entity, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_session().commit()

        return media_ids

    def save_downloaded_medias(
        self, medias: list[DownloadedMediaInfo], commit: bool = False
    ) -> list[int]:
        """
        Save multiple downloaded media entities.

        Args:
            medias: List of DownloadedMediaInfo objects
            commit: Whether to commit immediately (default: False)

        Returns list of media_ids.
        """
        media_ids = []
        for media in medias:
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
            media_id = self._save_media(media_entity, commit=False)
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
            author_id = self.save_author(
                result.author, platform_id, user_id, commit=False
            )

            # Check if parse result already exists globally by platform_id + pid
            stmt = select(ParseResult).where(
                (ParseResult.pid == result.pid)
                & (ParseResult.platform_id == platform_id)
            )
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
                    logger.info(
                        f"Restored soft-deleted parse result {existing_result.id}"
                    )
                session.flush()

                # Clear old media associations
                session.query(ParseResultMedia).filter(
                    ParseResultMedia.parse_result_id == parse_result_id
                ).delete()
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
                (UserParseResult.user_id == user_id)
                & (UserParseResult.parse_result_id == parse_result_id)
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()

            if not user_parse_result:
                # Create new association
                user_parse_result = UserParseResult(
                    user_id=user_id, parse_result_id=parse_result_id
                )
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

            # Save media associations
            self._save_media_associations(parse_result_id, result.media)

            # Commit all changes
            session.commit()

            return parse_result_id
        except Exception as e:
            session.rollback()
            raise Exception(
                f"Failed to save parse result (pid: {result.pid}, platform: {result.platform.code}): {e}"
            )

    def _save_media_associations(
        self, parse_result_id: int, media: list[ParserMediaInfo]
    ) -> None:
        """
        Helper method to save media associations for a parse result.

        Args:
            parse_result_id: Parse result ID
            media: List of media entities
        """
        session = self._get_session()
        # Save media
        media_ids = self.save_medias(media, commit=False)
        for order, media_id in enumerate(media_ids):
            assoc = ParseResultMedia(
                parse_result_id=parse_result_id, media_id=media_id, order=order
            )
            session.add(assoc)
        session.flush()

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
            raise ValueError(
                f"Parse result with id {parse_result_id} not found or access denied"
            )

        return ParseResultEntity.from_orm(result_orm)

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

        stmt = select(ParseResult).where(
            ParseResult.url == url, ParseResult.deleted_at.is_(None)
        )

        result_orm = session.execute(stmt).scalar_one_or_none()
        return ParseResultEntity.from_orm(result_orm) if result_orm else None

    def list_parse_results(
        self,
        user_id: int,
        platform_id: int | None = None,
        author_id: int | None = None,
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

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        results_orm = session.execute(query).scalars().all()

        results = [ParseResultEntity.from_orm(result_orm) for result_orm in results_orm]
        return results, total

    def sync_parse_results(
        self,
        user_id: int,
        last_sync_time: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ParseResultEntity], int]:
        """
        Sync parse results based on last sync time.
        Returns all parse results (including deleted ones in association table) that were created or updated after the last sync time.

        Args:
            user_id: Filter by user ID
            last_sync_time: Optional datetime of the last sync. If None, returns all results.
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns tuple of (list of ParseResultEntity objects with deleted_at field, total count).
        """
        session = self._get_session()

        # Build query with JOIN to UserParseResult (include soft-deleted associations)
        # Eagerly load media_list -> media to avoid N+1 lazy-load queries per result
        query = (
            select(ParseResult)
            .join(
                UserParseResult,
                (UserParseResult.parse_result_id == ParseResult.id)
                & (UserParseResult.user_id == user_id),
            )
            .options(
                selectinload(ParseResult.media_list).selectinload(
                    ParseResultMedia.media
                )
            )
        )

        # Filter by last_sync_time if provided
        if last_sync_time is not None:
            media_update_subquery = exists(
                select(1)
                .select_from(ParseResultMedia)
                .join(Media, ParseResultMedia.media_id == Media.id)
                .where(
                    ParseResultMedia.parse_result_id == ParseResult.id,
                    Media.updated_at > last_sync_time,
                )
            )
            query = query.where(
                or_(
                    ParseResult.updated_at > last_sync_time,
                    UserParseResult.updated_at > last_sync_time,
                    media_update_subquery,
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
        for result_orm in results_orm:
            # Check if association is deleted
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id)
                & (UserParseResult.parse_result_id == result_orm.id)
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()
            association_deleted_at = (
                user_parse_result.deleted_at if user_parse_result else None
            )

            # Convert to entity and override deleted_at if needed
            entity = ParseResultEntity.from_orm(result_orm)
            entity.deleted_at = association_deleted_at or result_orm.deleted_at

            # Use the latest updated_at across parse result, user association, and associated media.
            # This ensures the client's next last_sync_time advances correctly when the trigger
            # was a media update (media_update_subquery), preventing infinite re-sync.
            timestamps = [result_orm.updated_at]
            if user_parse_result and user_parse_result.updated_at:
                timestamps.append(user_parse_result.updated_at)
            for prm in result_orm.media_list:
                if prm.media and prm.media.updated_at:
                    timestamps.append(prm.media.updated_at)
            entity.updated_at = max(timestamps)
            results.append(entity)

        return results, total

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

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        platforms_orm = session.execute(query).scalars().all()

        platforms = [PlatformEntity.from_orm(p) for p in platforms_orm]
        return platforms, total

    def list_authors(
        self,
        user_id: int,
        platform_id: int | None = None,
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
        total = session.execute(count_query).scalar() or 0

        # Add sorting
        sort_field_map = {
            "name": Author.name,
            "created_at": Author.created_at,
            "updated_at": Author.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Author.id)

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        authors_orm = session.execute(query).scalars().all()

        authors = [AuthorEntity.from_orm(a) for a in authors_orm]
        return authors, total

    def delete_platform(
        self, user_id: int, platform_id: int, commit: bool = False
    ) -> tuple[bool, list[str]]:
        """
        Soft delete user's association with platform and cascade to related authors and parse results.
        Does NOT delete the platform itself as it's shared among users.

        Args:
            user_id: User ID performing the deletion
            platform_id: Platform ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        all_file_paths = []

        try:
            # Verify user-platform association exists
            stmt = select(UserPlatform).where(
                (UserPlatform.user_id == user_id)
                & (UserPlatform.platform_id == platform_id)
                & (UserPlatform.deleted_at.is_(None))
            )
            user_platform = session.execute(stmt).scalar_one_or_none()

            if not user_platform:
                logger.warning(
                    f"Platform {platform_id} not found or already deleted for user {user_id}"
                )
                return False, all_file_paths

            # Get all authors belonging to this platform for this user
            stmt = (
                select(Author.id)
                .join(
                    UserAuthor,
                    (UserAuthor.author_id == Author.id)
                    & (UserAuthor.user_id == user_id)
                    & (UserAuthor.deleted_at.is_(None)),
                )
                .where(
                    (Author.platform_id == platform_id) & (Author.deleted_at.is_(None))
                )
            )
            author_ids = session.execute(stmt).scalars().all()

            logger.debug(
                f"Soft deleting user {user_id}'s platform {platform_id} with {len(author_ids)} authors"
            )

            # Soft delete each author association
            for author_id in author_ids:
                success, file_paths = self.delete_author(
                    user_id, author_id, commit=False
                )
                all_file_paths.extend(file_paths)

            # Soft delete user-platform association
            user_platform.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, all_file_paths

        except Exception as e:
            if commit:
                session.rollback()
            logger.exception(
                f"Database error when soft deleting platform {platform_id} for user {user_id}"
            )
            raise Exception(f"Failed to soft delete platform association: {e}")

    def delete_author(
        self, user_id: int, author_id: int, commit: bool = False
    ) -> tuple[bool, list[str]]:
        """
        Soft delete user's association with author and cascade to related parse results.
        Does NOT delete the author itself as it's shared among users.

        Args:
            user_id: User ID performing the deletion
            author_id: Author ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        all_file_paths = []

        try:
            # Verify user-author association exists
            stmt = select(UserAuthor).where(
                (UserAuthor.user_id == user_id)
                & (UserAuthor.author_id == author_id)
                & (UserAuthor.deleted_at.is_(None))
            )
            user_author = session.execute(stmt).scalar_one_or_none()

            if not user_author:
                logger.warning(
                    f"Author {author_id} not found or already deleted for user {user_id}"
                )
                return False, all_file_paths

            # Get all parse result IDs for this author for this user
            stmt = (
                select(ParseResult.id)
                .join(
                    UserParseResult,
                    (UserParseResult.parse_result_id == ParseResult.id)
                    & (UserParseResult.user_id == user_id)
                    & (UserParseResult.deleted_at.is_(None)),
                )
                .where(
                    (ParseResult.author_id == author_id)
                    & (ParseResult.deleted_at.is_(None))
                )
            )
            parse_result_ids = session.execute(stmt).scalars().all()

            logger.debug(
                f"Soft deleting user {user_id}'s author {author_id} with {len(parse_result_ids)} parse results"
            )

            # Soft delete each parse result association
            for pr_id in parse_result_ids:
                success, file_paths = self.delete_parse_result(
                    user_id, pr_id, commit=False
                )
                all_file_paths.extend(file_paths)

            # Soft delete user-author association
            user_author.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, all_file_paths

        except Exception as e:
            if commit:
                session.rollback()
            logger.exception(
                f"Database error when soft deleting author {author_id} for user {user_id}"
            )
            raise Exception(f"Failed to soft delete author association: {e}")

    def delete_parse_result(
        self, user_id: int, parse_result_id: int, commit: bool = False
    ) -> tuple[bool, list[str]]:
        """
        Soft delete user's association with parse result.
        Does NOT delete the parse result or media themselves as they're shared among users.
        Only deletes media files if they become completely orphaned (no active associations).

        Args:
            user_id: User ID performing the deletion
            parse_result_id: Parse result ID to delete association with
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        file_paths = []

        try:
            # Verify user-parse_result association exists
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id)
                & (UserParseResult.parse_result_id == parse_result_id)
                & (UserParseResult.deleted_at.is_(None))
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()

            if not user_parse_result:
                logger.warning(
                    f"Parse result {parse_result_id} not found or already deleted for user {user_id}"
                )
                raise ValueError(
                    f"Parse result {parse_result_id} not found or already deleted"
                )

            # Get parse result to check media
            result_orm = (
                session.query(ParseResult)
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

            # If parse result becomes orphaned, collect media paths and clean up
            if other_users_count == 0:
                logger.debug(
                    f"Parse result {parse_result_id} will be orphaned, collecting media"
                )

                # Get orphaned media IDs (only used by this parse result and not by other active results)
                orphaned_media_ids = []
                for prm in result_orm.media_list:
                    media_id = prm.media_id
                    # Check if this media is used by other parse results with active user associations
                    count = (
                        session.query(func.count(ParseResultMedia.parse_result_id))
                        .join(ParseResult)
                        .join(
                            UserParseResult,
                            (UserParseResult.parse_result_id == ParseResult.id)
                            & (UserParseResult.deleted_at.is_(None)),
                        )
                        .filter(
                            ParseResultMedia.media_id == media_id,
                            ParseResult.deleted_at.is_(None),
                            ParseResult.id != parse_result_id,
                        )
                        .scalar()
                    )
                    if count == 0:  # Only used by this parse result
                        orphaned_media_ids.append(media_id)

                # Collect media paths ONLY for orphaned media
                if orphaned_media_ids:
                    orphaned_media = (
                        session.query(Media)
                        .filter(Media.id.in_(orphaned_media_ids))
                        .all()
                    )
                    for media in orphaned_media:
                        if media.media_path:
                            file_paths.append(media.media_path)
                        if media.cover_path:
                            file_paths.append(media.cover_path)

                # Hard delete orphaned media and associations
                session.query(ParseResultMedia).filter(
                    ParseResultMedia.parse_result_id == parse_result_id
                ).delete()

                if orphaned_media_ids:
                    session.query(Media).filter(
                        Media.id.in_(orphaned_media_ids)
                    ).delete()
                    logger.debug(
                        f"Hard deleted {len(orphaned_media_ids)} orphaned media records"
                    )

                # Also soft delete the parse result itself if it's orphaned
                result_orm.deleted_at = datetime.now(UTC)

            # Soft delete user-parse_result association
            user_parse_result.deleted_at = datetime.now(UTC)
            session.flush()

            if commit:
                session.commit()

            return True, file_paths

        except Exception:
            if commit:
                session.rollback()
            logger.exception(
                f"Unexpected error when soft deleting parse result {parse_result_id} for user {user_id}"
            )
            raise
