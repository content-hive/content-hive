from datetime import UTC, datetime

from sqlalchemy import Integer, cast, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import (
    Author,
    Media,
    ParseResult,
    Platform,
    UserAuthor,
    UserMedia,
    UserParseResult,
    UserPlatform,
)
from contenthive.database.tag_dao import TagDAO
from contenthive.logger import logger
from contenthive.models.content import (
    AuthorEntity,
    DownloadedMediaInfo,
    MediaEntity,
    ParseResultEntity,
    PlatformEntity,
)
from contenthive.models.enumerates import MediaStatus
from contenthive.models.tag import TagEntity
from contenthive.plugins.contracts import (
    ParserAuthorInfo,
    ParserMediaInfo,
    ParserPlatformInfo,
    ParserResult,
)
from contenthive.utils.content import ContentDirectory, resolve_content_id


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
                # Restore soft-deleted association; reset created_at so "recently added"
                # reflects when the user re-added this content.
                now = datetime.now(UTC)
                user_parse_result.deleted_at = None
                user_parse_result.created_at = now
                user_parse_result.updated_at = now
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
        tag_ids = list(user_parse_result.tags or []) if user_parse_result else []
        with TagDAO(session=session) as tag_dao:
            tags = tag_dao.resolve_tags_for_ids(user_id, tag_ids)
            entity = ParseResultEntity.from_orm(result_orm, tags=tags)
            if user_parse_result is not None:
                entity.created_at = user_parse_result.created_at
            media_ids = [media.id for media in result_orm.media]
            self._apply_media_tags_to_entity(entity, tag_dao.load_media_tags_map(user_id, media_ids))
            self._apply_author_tags_to_entity(entity, tag_dao.load_author_tags_map(user_id, [result_orm.author_id]))
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

        # Add sorting (id tie-breaker keeps offset pages stable when sort values collide).
        # created_at uses the per-user association time (when the user added/restored the content).
        if sort_by == "post_time":
            sort_field = ParseResult.post_time
        elif sort_by == "updated_at":
            sort_field = ParseResult.updated_at
        elif sort_by == "id":
            sort_field = ParseResult.id
        else:
            sort_field = UserParseResult.created_at

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc(), ParseResult.id.asc())
        else:
            query = query.order_by(sort_field.desc(), ParseResult.id.desc())

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

        # Sort by updated_at desc (most recent first); id tie-breaker for stable pages
        query = query.order_by(ParseResult.updated_at.desc(), ParseResult.id.desc())

        query = query.limit(limit).offset(offset)
        results_orm = session.execute(query).scalars().all()

        results = []
        media_ids = [media.id for result_orm in results_orm for media in result_orm.media]
        author_ids = [result_orm.author_id for result_orm in results_orm]
        with TagDAO(session=session) as tag_dao:
            media_tag_ids_map = tag_dao.load_media_tag_ids_map(user_id, media_ids)
            user_media_updated = tag_dao.load_user_media_updated_at(user_id, media_ids)
            author_tag_ids_map = tag_dao.load_author_tag_ids_map(user_id, author_ids)
            user_author_updated = tag_dao.load_user_author_updated_at(user_id, author_ids)

        for result_orm in results_orm:
            # Check if association is deleted
            stmt = select(UserParseResult).where(
                (UserParseResult.user_id == user_id) & (UserParseResult.parse_result_id == result_orm.id)
            )
            user_parse_result = session.execute(stmt).scalar_one_or_none()
            association_deleted_at = user_parse_result.deleted_at if user_parse_result else None

            # Sync only needs IDs from association JSON — skip tags-table resolve.
            raw_tags = list(user_parse_result.tags or []) if user_parse_result else []
            tag_ids = list(dict.fromkeys(int(tid) for tid in raw_tags))

            # Convert to entity and override deleted_at if needed
            entity = ParseResultEntity.from_orm(result_orm)
            entity.tag_ids = tag_ids
            for media in entity.media:
                if media.id is None:
                    continue
                media.tag_ids = list(media_tag_ids_map.get(media.id, []))
            if entity.author.id is not None:
                entity.author.tag_ids = list(author_tag_ids_map.get(entity.author.id, []))
            entity.deleted_at = association_deleted_at or result_orm.deleted_at
            if user_parse_result is not None:
                entity.created_at = user_parse_result.created_at

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
        created_at_by_result = {association.parse_result_id: association.created_at for association in associations}

        all_tag_ids: list[int] = []
        for ids in tags_by_result.values():
            all_tag_ids.extend(ids)
        with TagDAO(session=session) as tag_dao:
            resolved = {tag.id: tag for tag in tag_dao.resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}
            media_ids = [media.id for result in results_orm for media in result.media]
            media_tags_map = tag_dao.load_media_tags_map(user_id, media_ids)
            author_ids = [result.author_id for result in results_orm]
            author_tags_map = tag_dao.load_author_tags_map(user_id, author_ids)

        entities: list[ParseResultEntity] = []
        for result_orm in results_orm:
            tag_ids = tags_by_result.get(result_orm.id, [])
            tags = [resolved[tid] for tid in dict.fromkeys(tag_ids) if tid in resolved]
            entity = ParseResultEntity.from_orm(result_orm, tags=tags)
            if result_orm.id in created_at_by_result:
                entity.created_at = created_at_by_result[result_orm.id]
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

        # Add sorting (id tie-breaker keeps offset pages stable when sort values collide)
        sort_field_map = {
            "name": Platform.name,
            "created_at": Platform.created_at,
            "updated_at": Platform.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Platform.id)

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc(), Platform.id.asc())
        else:
            query = query.order_by(sort_field.desc(), Platform.id.desc())

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

        # Add sorting (id tie-breaker keeps offset pages stable when sort values collide)
        sort_field_map = {
            "name": Author.name,
            "created_at": Author.created_at,
            "updated_at": Author.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Author.id)

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc(), Author.id.asc())
        else:
            query = query.order_by(sort_field.desc(), Author.id.desc())

        query = query.limit(limit).offset(offset)
        authors_orm = session.execute(query).scalars().all()

        author_ids = [author.id for author in authors_orm]
        with TagDAO(session=session) as tag_dao:
            author_tags_map = tag_dao.load_author_tags_map(user_id, author_ids)
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
