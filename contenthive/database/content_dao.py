from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import exists, or_, select, func
from sqlalchemy.orm import Session

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import (
    Platform, Author, Media, ParseResult, ParseResultMedia
)
from contenthive.models.content import (
    DownloadedMediaInfo,
    ParseResultEntity, 
    AuthorEntity,
    PlatformEntity, 
    MediaEntity     
)
from contenthive.models.parser import ParserAuthorInfo, ParserMediaInfo, ParserPlatformInfo, ParserResult
from contenthive.logger import logger


class ParserDAO:
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
        Save or update platform information.

        Args:
            platform: Platform entity
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns platform_id.
        """
        session = self._get_session()
        try:
            # Check if platform exists (including soft-deleted ones)
            stmt = select(Platform).where(
                (Platform.user_id == user_id) & (Platform.code == platform.code)
            )
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
                    user_id=user_id,
                    code=platform.code,
                    name=platform.name,
                    url=str(platform.url),
                    icon_url=str(platform.icon_url) if platform.icon_url else None
                )
                session.add(new_platform)
                session.flush()
                platform_id = new_platform.id

            if commit:
                session.commit()

            return platform_id
        except Exception as e:
            if commit:
                session.rollback()
            raise Exception(f"Failed to save platform: {e}")

    def save_author(self, author: ParserAuthorInfo, platform_id: int, user_id: int, commit: bool = False) -> int:
        """
        Save or update author information.

        Args:
            author: Author entity
            platform_id: Platform ID
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns author_id.
        """
        session = self._get_session()
        try:
            # Check if author exists (including soft-deleted ones)
            stmt = select(Author).where(
                (Author.user_id == user_id) & 
                (Author.platform_id == platform_id) & 
                (Author.uid == author.uid)
            )
            existing_author = session.execute(stmt).scalar_one_or_none()

            if existing_author:
                # Update existing author
                existing_author.name = author.name
                existing_author.username = author.username
                existing_author.avatar = str(author.avatar) if author.avatar else None
                existing_author.url = str(author.url) if author.url else None
                # Restore if soft-deleted
                if existing_author.deleted_at is not None:
                    existing_author.deleted_at = None
                    logger.info(f"Restored soft-deleted author {existing_author.id}")
                session.flush()
                author_id = existing_author.id
            else:
                # Insert new author
                new_author = Author(
                    user_id=user_id,
                    platform_id=platform_id,
                    uid=author.uid,
                    name=author.name,
                    username=author.username,
                    avatar=str(author.avatar) if author.avatar else None,
                    url=str(author.url) if author.url else None
                )
                session.add(new_author)
                session.flush()
                author_id = new_author.id

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
                existing_media.status = media.status
                # Update existing media if paths are provided
                if media.media_path or media.cover_path:
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
                return existing_media.id

            # Insert new media
            new_media = Media(
                url=media.url,
                type=media.type,
                title=media.title,
                cover=media.cover,
                duration=media.duration,
                width=media.width,
                height=media.height,
                media_path=media.media_path,
                cover_path=media.cover_path,
                status=media.status
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

    def save_medias(self, medias: list[ParserMediaInfo], commit: bool = False) -> list[int]:
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
                status="pending",  # Default to pending when saving from parser result
                url=str(media.url),
                type=str(media.type) if media.type else "",
                title=media.title,
                cover=str(media.cover) if media.cover else None
            )
            media_id = self._save_media(media_entity, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_session().commit()

        return media_ids

    def save_downloaded_medias(self, medias: list[DownloadedMediaInfo], commit: bool = False) -> list[int]:
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
                type=str(media.type) if media.type else "",
                title=media.title,
                cover=str(media.cover) if media.cover else None,
                duration=media.duration,
                width=media.width,
                height=media.height,
                media_path=media.media_path,
                cover_path=media.cover_path
            )
            media_id = self._save_media(media_entity, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_session().commit()

        return media_ids

    def save_parse_result(self, result: ParserResult, user_id: int) -> int:
        """
        Save complete parse result including platform, author, and media.
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

            # Check if parse result already exists using pid and platform code (including soft-deleted ones)
            stmt = select(ParseResult).where(
                (ParseResult.user_id == user_id) &
                (ParseResult.pid == result.pid) &
                (ParseResult.platform_id == platform_id)
            )
            existing_result = session.execute(stmt).scalar_one_or_none()

            if existing_result:
                parse_result_id = existing_result.id
                # Update existing parse result
                existing_result.url = str(result.url)
                existing_result.content = result.content
                existing_result.post_time = result.post_time
                existing_result.parser = result.parser
                existing_result.state = result.state
                # Restore if soft-deleted
                if existing_result.deleted_at is not None:
                    existing_result.deleted_at = None
                    logger.info(f"Restored soft-deleted parse result {existing_result.id}")
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
                    content=result.content,
                    author_id=author_id,
                    platform_id=platform_id,
                    user_id=user_id,
                    post_time=result.post_time,
                    parser=result.parser,
                    state=result.state
                )
                session.add(new_result)
                session.flush()
                parse_result_id = new_result.id

            # Save media associations
            self._save_media_associations(parse_result_id, result.media)

            # Commit all changes
            session.commit()

            return parse_result_id
        except Exception as e:
            session.rollback()
            raise Exception(f"Failed to save parse result (pid: {result.pid}, platform: {result.platform.code}): {e}")

    def _save_media_associations(self, parse_result_id: int, media: list[ParserMediaInfo]) -> None:
        """
        Helper method to save media associations for a parse result.
        
        Args:
            parse_result_id: Parse result ID
            media: List of media entities
        """
        session = self._get_session()
        # Save media
        media_ids = self.save_medias(media, commit=False)
        for media_id in media_ids:
            assoc = ParseResultMedia(
                parse_result_id=parse_result_id,
                media_id=media_id
            )
            session.add(assoc)
        session.flush()

    def _orm_to_media_entity(self, media_orm: Media) -> MediaEntity:
        """Convert ORM media object to entity"""
        return MediaEntity(
            id=media_orm.id,
            status=media_orm.status,
            url=media_orm.url,
            type=media_orm.type,
            title=media_orm.title,
            duration=media_orm.duration,
            width=media_orm.width,
            height=media_orm.height,
            cover=media_orm.cover,
            media_path=media_orm.media_path,
            cover_path=media_orm.cover_path,
            created_at=media_orm.created_at,
            updated_at=media_orm.updated_at
        )

    def _orm_to_platform_entity(self, platform_orm: Platform) -> PlatformEntity:
        """Convert ORM platform object to entity"""
        return PlatformEntity(
            id=platform_orm.id,
            code=platform_orm.code,
            name=platform_orm.name,
            url=platform_orm.url,
            icon_url=platform_orm.icon_url,
            created_at=platform_orm.created_at,
            updated_at=platform_orm.updated_at
        )

    def _orm_to_author_entity(self, author_orm: Author, platform: Optional[Platform] = None) -> AuthorEntity:
        """Convert ORM author object to entity"""
        platform_entity = None
        if author_orm.platform or platform:
            p = author_orm.platform or platform
            platform_entity = self._orm_to_platform_entity(p)
        
        if not platform_entity:
            raise ValueError("Author's platform information is missing, cannot convert to AuthorEntity")
        
        return AuthorEntity(
            id=author_orm.id,
            platform_id=author_orm.platform_id,
            uid=author_orm.uid,
            name=author_orm.name,
            username=author_orm.username,
            avatar=author_orm.avatar,
            url=author_orm.url,
            created_at=author_orm.created_at,
            updated_at=author_orm.updated_at,
            platform=platform_entity
        )

    def get_parse_result(self, parse_result_id: int) -> ParseResultEntity:
        """
        Get parse result entity by ID.
        Returns ParseResultEntity object.
        """
        session = self._get_session()
        
        result_orm = session.query(ParseResult).filter(
            ParseResult.id == parse_result_id,
            ParseResult.deleted_at.is_(None)
        ).first()
        if not result_orm:
            raise ValueError(f"Parse result with id {parse_result_id} not found")

        # Get media
        media_list = []
        for prm in result_orm.media_list:
            media_list.append(self._orm_to_media_entity(prm.media))

        platform = self._orm_to_platform_entity(result_orm.platform if hasattr(result_orm, 'platform') else None)
        author = self._orm_to_author_entity(result_orm.author if hasattr(result_orm, 'author') else None, result_orm.platform)

        # Build entity
        entity = ParseResultEntity(
            id=result_orm.id,
            pid=result_orm.pid,
            url=result_orm.url,
            content=result_orm.content,
            author_id=result_orm.author_id,
            platform_id=result_orm.platform_id,
            user_id=result_orm.user_id,
            post_time=result_orm.post_time,
            parser=result_orm.parser,
            state=result_orm.state,
            created_at=result_orm.created_at,
            updated_at=result_orm.updated_at,
            author=author,
            platform=platform,
            media=media_list
        )

        return entity

    def list_parse_results(self, user_id: int,
                          platform_id: Optional[int] = None,
                          author_id: Optional[int] = None,
                          limit: int = 20, offset: int = 0,
                          sort_by: str = "created_at", order: str = "desc") -> tuple[list[ParseResultEntity], int]:
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

        # Build WHERE clause
        query = select(ParseResult).where(
            ParseResult.user_id == user_id,
            ParseResult.deleted_at.is_(None)
        )

        if platform_id is not None:
            query = query.where(ParseResult.platform_id == platform_id)

        if author_id is not None:
            query = query.where(ParseResult.author_id == author_id)

        # Get total count
        total = session.query(func.count(ParseResult.id)).where(
            ParseResult.user_id == user_id,
            ParseResult.deleted_at.is_(None)
        )
        if platform_id is not None:
            total = total.where(ParseResult.platform_id == platform_id)
        if author_id is not None:
            total = total.where(ParseResult.author_id == author_id)
        total = total.scalar()

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

        results = []
        for result_orm in results_orm:
            # Get media
            media_list = []
            for prm in result_orm.media_list:
                media_list.append(self._orm_to_media_entity(prm.media))

            platform = self._orm_to_platform_entity(result_orm.platform)
            author = self._orm_to_author_entity(result_orm.author, result_orm.platform)

            entity = ParseResultEntity(
                id=result_orm.id,
                pid=result_orm.pid,
                url=result_orm.url,
                content=result_orm.content,
                author_id=result_orm.author_id,
                platform_id=result_orm.platform_id,
                user_id=result_orm.user_id,
                post_time=result_orm.post_time,
                parser=result_orm.parser,
                state=result_orm.state,
                created_at=result_orm.created_at,
                updated_at=result_orm.updated_at,
                author=author,
                platform=platform,
                media=media_list
            )
            results.append(entity)

        return results, total

    def sync_parse_results(self, user_id: int,
                          last_sync_time: Optional[datetime] = None,
                          limit: int = 20, offset: int = 0) -> tuple[list[ParseResultEntity], int]:
        """
        Sync parse results based on last sync time.
        Returns all parse results (including deleted ones) that were created or updated after the last sync time.
    
        Args:
            user_id: Filter by user ID
            last_sync_time: Optional datetime of the last sync. If None, returns all results.
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns tuple of (list of ParseResultEntity objects with deleted_at field, total count).
        """
        session = self._get_session()

        # Build WHERE clause - NOTE: We do NOT filter by deleted_at to include deleted records
        query = select(ParseResult).where(
            ParseResult.user_id == user_id
        )

        # Filter by last_sync_time if provided
        if last_sync_time is not None:
            media_update_subquery = exists(
                select(1)
                .select_from(ParseResultMedia)
                .join(Media, ParseResultMedia.media_id == Media.id)
                .where(
                    ParseResultMedia.parse_result_id == ParseResult.id,
                    Media.updated_at > last_sync_time
                )
            )
            query = query.where(
                or_(
                    ParseResult.updated_at > last_sync_time,
                    media_update_subquery
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
            # Get media
            media_list = []
            for prm in result_orm.media_list:
                media_list.append(self._orm_to_media_entity(prm.media))

            platform = self._orm_to_platform_entity(result_orm.platform)
            author = self._orm_to_author_entity(result_orm.author, result_orm.platform)

            entity = ParseResultEntity(
                id=result_orm.id,
                pid=result_orm.pid,
                url=result_orm.url,
                content=result_orm.content,
                author_id=result_orm.author_id,
                platform_id=result_orm.platform_id,
                user_id=result_orm.user_id,
                post_time=result_orm.post_time,
                parser=result_orm.parser,
                state=result_orm.state,
                created_at=result_orm.created_at,
                updated_at=result_orm.updated_at,
                deleted_at=result_orm.deleted_at,
                author=author,
                platform=platform,
                media=media_list
            )
            results.append(entity)

        return results, total

    def list_platforms(self, user_id: int, limit: int = 100, offset: int = 0,
                       sort_by: str = "id", order: str = "asc") -> tuple[list[PlatformEntity], int]:
        """
        List all platforms with pagination and sorting.
        
        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip
            sort_by: Field to sort by (id, name, created_at, updated_at)
            order: Sort order (asc, desc)
            
        Returns tuple of (list of PlatformEntity objects, total count).
        """
        session = self._get_session()

        # Get total count
        total = session.query(func.count(Platform.id)).where(
            Platform.user_id == user_id,
            Platform.deleted_at.is_(None)
        ).scalar()

        # Build query
        query = select(Platform).where(
            Platform.user_id == user_id,
            Platform.deleted_at.is_(None)
        )

        # Add sorting
        sort_field_map = {
            "name": Platform.name,
            "created_at": Platform.created_at,
            "updated_at": Platform.updated_at
        }
        sort_field = sort_field_map.get(sort_by, Platform.id)

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        platforms_orm = session.execute(query).scalars().all()

        platforms = [self._orm_to_platform_entity(p) for p in platforms_orm]
        return platforms, total

    def list_authors(self, user_id: int, platform_id: Optional[int] = None,
                    limit: int = 100, offset: int = 0,
                    sort_by: str = "id", order: str = "asc") -> tuple[list[AuthorEntity], int]:
        """
        List authors with pagination and sorting, optionally filtered by platform_id.
        
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

        # Build query
        query = select(Author).where(
            Author.user_id == user_id,
            Author.deleted_at.is_(None)
        )

        if platform_id is not None:
            query = query.where(Author.platform_id == platform_id)

        # Get total count
        total = session.query(func.count(Author.id)).where(
            Author.user_id == user_id,
            Author.deleted_at.is_(None)
        )
        if platform_id is not None:
            total = total.where(Author.platform_id == platform_id)
        total = total.scalar()

        # Add sorting
        sort_field_map = {
            "name": Author.name,
            "created_at": Author.created_at,
            "updated_at": Author.updated_at
        }
        sort_field = sort_field_map.get(sort_by, Author.id)

        if order.lower() == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

        query = query.limit(limit).offset(offset)
        authors_orm = session.execute(query).scalars().all()

        authors = [self._orm_to_author_entity(a) for a in authors_orm]
        return authors, total

    def delete_platform(self, user_id: int, platform_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Soft delete platform by ID and cascade soft delete related authors and parse results.
        
        Args:
            user_id: User ID performing the deletion
            platform_id: Platform ID to delete
            commit: Whether to commit immediately (default: False)
            
        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        all_file_paths = []
        
        try:
            # First verify ownership/existence of platform
            platform_orm = session.query(Platform).where(
                (Platform.id == platform_id) & 
                (Platform.user_id == user_id) & 
                (Platform.deleted_at.is_(None))
            ).first()
            
            if not platform_orm:
                logger.warning(f"Platform {platform_id} not found or access denied for user {user_id}")
                return False, all_file_paths
            
            # Get all authors belonging to this platform (not already deleted)
            authors = session.query(Author).filter(
                (Author.user_id == user_id) & 
                (Author.platform_id == platform_id) &
                (Author.deleted_at.is_(None))
            ).all()
            
            logger.info(f"Soft deleting platform {platform_id} with {len(authors)} authors")
            
            # Soft delete each author (which will collect file paths)
            for author in authors:
                success, file_paths = self.delete_author(user_id, author.id, commit=False)
                all_file_paths.extend(file_paths)
            
            # Soft delete platform
            platform_orm.deleted_at = datetime.now(timezone.utc)
            session.flush()
            
            if commit:
                session.commit()
                logger.info(f"Successfully soft deleted platform {platform_id} from database")
            
            return True, all_file_paths
            
        except Exception as e:
            if commit:
                session.rollback()
            logger.error(f"Database error when soft deleting platform {platform_id}: {e}")
            raise Exception(f"Failed to soft delete platform: {e}")

    def delete_author(self, user_id: int, author_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Soft delete author by ID and cascade soft delete related parse results.
        
        Args:
            user_id: User ID performing the deletion
            author_id: Author ID to delete
            commit: Whether to commit immediately (default: False)
            
        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        all_file_paths = []
        
        try:
            # First verify ownership/existence of author
            author_orm = session.query(Author).where(
                (Author.id == author_id) & 
                (Author.user_id == user_id) &
                (Author.deleted_at.is_(None))
            ).first()
            
            if not author_orm:
                logger.warning(f"Author {author_id} not found or access denied for user {user_id}")
                return False, all_file_paths
            
            # Get all parse result IDs for this author (not already deleted)
            parse_results = session.query(ParseResult).filter(
                (ParseResult.user_id == user_id) & 
                (ParseResult.author_id == author_id) &
                (ParseResult.deleted_at.is_(None))
            ).all()
            
            logger.info(f"Soft deleting author {author_id} with {len(parse_results)} parse results")

            # Soft delete each parse result (which will collect file paths)
            for pr in parse_results:
                success, file_paths = self.delete_parse_result(user_id, pr.id, commit=False)
                all_file_paths.extend(file_paths)

            # Soft delete author
            author_orm.deleted_at = datetime.now(timezone.utc)
            session.flush()
            
            if commit:
                session.commit()
                logger.info(f"Successfully soft deleted author {author_id} from database")
            
            return True, all_file_paths
            
        except Exception as e:
            if commit:
                session.rollback()
            logger.error(f"Database error when soft deleting author {author_id}: {e}")
            raise Exception(f"Failed to soft delete author: {e}")

    def delete_parse_result(self, user_id: int, parse_result_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Soft delete parse result by ID and return list of associated media file paths.
        Media and ParseResultMedia are still hard deleted if orphaned.

        Args:
            user_id: User ID performing the deletion
            parse_result_id: Parse result ID to delete
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        session = self._get_session()
        file_paths = []

        try:
            # 1. FIRST verify ownership/existence of parse result
            result_orm = session.query(ParseResult).where(
                (ParseResult.id == parse_result_id) & 
                (ParseResult.user_id == user_id) &
                (ParseResult.deleted_at.is_(None))
            ).first()
            
            if not result_orm:
                logger.warning(f"Parse result {parse_result_id} not found or access denied for user {user_id}")
                raise ValueError(f"Parse result {parse_result_id} not found or access denied")
            
            # 2. Get orphaned media IDs (only used by this parse result and not used by non-deleted results)
            orphaned_media_ids = []
            for prm in result_orm.media_list:
                media_id = prm.media_id
                # Check if this media is used by other non-deleted parse results
                count = session.query(func.count(ParseResultMedia.parse_result_id)).join(
                    ParseResult
                ).filter(
                    ParseResultMedia.media_id == media_id,
                    ParseResult.deleted_at.is_(None),
                    ParseResult.id != parse_result_id
                ).scalar()
                if count == 0:  # Only used by this parse result
                    orphaned_media_ids.append(media_id)

            # 3. Collect media paths ONLY for orphaned media
            if orphaned_media_ids:
                orphaned_media = session.query(Media).filter(Media.id.in_(orphaned_media_ids)).all()
                for media in orphaned_media:
                    if media.media_path:
                        file_paths.append(media.media_path)
                    if media.cover_path:
                        file_paths.append(media.cover_path)

            # 4. Hard delete orphaned media and associations
            session.query(ParseResultMedia).filter(
                ParseResultMedia.parse_result_id == parse_result_id
            ).delete()

            if orphaned_media_ids:
                session.query(Media).filter(Media.id.in_(orphaned_media_ids)).delete()
                logger.debug(f"Hard deleted {len(orphaned_media_ids)} orphaned media records")

            # 5. Soft delete parse result
            result_orm.deleted_at = datetime.now(timezone.utc)
            session.flush()
            
            # 6. Commit if requested
            if commit:
                session.commit()
                logger.info(f"Soft deleted parse result {parse_result_id} from database")

            return True, file_paths

        except Exception as e:
            if commit:
                session.rollback()
            logger.error(f"Unexpected error when soft deleting parse result {parse_result_id}: {e}")
            raise
