import sqlite3
from typing import Optional
from contenthive.database.database import get_db_connection
from contenthive.models.content import (
    ParseResultEntity, 
    AuthorEntity,
    PlatformEntity, 
    MediaEntity,
    ParserMapper,     
)
from contenthive.models.parser import ParserResult
from contenthive.logger import logger

class ParserDAO:
    """
    Data Access Object for parser-related database operations.
    """

    def __init__(self):
        self.conn = None

    def __enter__(self):
        self._get_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        if self.conn is None:
            self.conn = get_db_connection()
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def save_platform(self, platform: PlatformEntity, user_id: int, commit: bool = False) -> int:
        """
        Save or update platform information.

        Args:
            platform: Platform entity
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns platform_id.
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()

            # Check if platform exists
            cursor.execute("SELECT id FROM platforms WHERE user_id = ? AND code = ?", (user_id, platform.code))
            result = cursor.fetchone()

            if result:
                # Update existing platform
                cursor.execute("""
                    UPDATE platforms
                    SET name = ?, url = ?, icon_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND code = ?
                """, (platform.name, platform.url, platform.icon_url, user_id, platform.code))
                platform_id = result[0]
            else:
                # Insert new platform
                cursor.execute("""
                    INSERT INTO platforms (user_id, code, name, url, icon_url)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, platform.code, platform.name, platform.url, platform.icon_url))
                platform_id = cursor.lastrowid if cursor.lastrowid else 0

            if commit:
                conn.commit()

            return platform_id
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            raise Exception(f"Failed to save platform: {e}")


    def save_author(self, author: AuthorEntity, platform_id: int, user_id: int, commit: bool = False) -> int:
        """
        Save or update author information.

        Args:
            author: Author entity
            platform_id: Platform ID
            user_id: User ID
            commit: Whether to commit immediately (default: False)

        Returns author_id.
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()

            # Check if author exists
            cursor.execute(
                "SELECT id FROM authors WHERE user_id = ? AND platform_id = ? AND uid = ?",
                (user_id, platform_id, author.uid)
            )
            result = cursor.fetchone()

            if result:
                # Update existing author
                cursor.execute("""
                    UPDATE authors
                    SET name = ?, username = ?, avatar = ?, url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND platform_id = ? AND uid = ?
                """, (author.name, author.username, author.avatar, author.url, user_id, platform_id, author.uid))
                author_id = result[0]
            else:
                # Insert new author
                cursor.execute("""
                    INSERT INTO authors (user_id, platform_id, uid, name, username, avatar, url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, platform_id, author.uid, author.name, author.username, author.avatar, author.url))
                author_id = cursor.lastrowid if cursor.lastrowid else 0

            if commit:
                conn.commit()

            return author_id
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            raise Exception(f"Failed to save author: {e}")


    def save_media(self, media: MediaEntity, commit: bool = False) -> int:
        """
        Save media information.

        Args:
            media: Media entity
            commit: Whether to commit immediately (default: False)

        Returns media_id.
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()

            # Check if media exists
            cursor.execute("SELECT id FROM media WHERE url = ?", (media.url,))
            result = cursor.fetchone()

            if result:
                # Update existing media if paths are provided
                if media.media_path or media.cover_path:
                    cursor.execute("""
                        UPDATE media
                        SET media_path = COALESCE(?, media_path),
                            cover_path = COALESCE(?, cover_path)
                        WHERE id = ?
                    """, (media.media_path, media.cover_path, result[0]))
                return result[0]

            # Insert new media
            cursor.execute("""
                INSERT INTO media (url, type, title, duration, width, height, cover, media_path, cover_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (media.url, media.type, media.title, media.duration, media.width, media.height, 
                   media.cover, media.media_path, media.cover_path))

            media_id = cursor.lastrowid if cursor.lastrowid else 0

            if commit:
                conn.commit()

            return media_id
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            raise Exception(f"Failed to save media: {e}")

    def save_medias(self, medias: list[MediaEntity], commit: bool = False) -> list[int]:
        """
        Save multiple media entities.

        Args:
            medias: List of MediaEntity objects
            commit: Whether to commit immediately (default: False)

        Returns list of media_ids.
        """
        media_ids = []
        for media in medias:
            media_id = self.save_media(media, commit=False)
            media_ids.append(media_id)

        if commit:
            self._get_connection().commit()

        return media_ids

    def save_parse_result(self, result: ParserResult, user_id: int) -> int:
        """
        Save complete parse result including platform, author, and media.
        Uses a single transaction for all operations.

        Args:
            result: ParserResult from parser
            user_id: User ID

        Returns the saved URLParserResult from database.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Convert parser models to entities
            platform_entity = ParserMapper.parser_platform_to_entity(result.platform)
            author_entity = ParserMapper.parser_author_to_entity(result.author, 0)  # platform_id will be set later
        
            # Save platform and get ID
            platform_id = self.save_platform(platform_entity, user_id, commit=False)
            
            # Update author entity with correct platform_id
            author_entity.platform_id = platform_id
            author_id = self.save_author(author_entity, user_id, platform_id, commit=False)

            # Convert ParserResult to ParseResultEntity
            entity = ParserMapper.parser_result_to_entity(
                result, platform_entity, author_entity, user_id
            )
            entity.platform_id = platform_id
            entity.author_id = author_id

            # Check if parse result already exists using pid and platform code
            cursor.execute("""
                SELECT pr.id 
                FROM parse_results pr
                JOIN platforms p ON pr.platform_id = p.id
                WHERE pr.user_id = ? AND pr.pid = ? AND p.code = ?
            """, (user_id, entity.pid, result.platform.code))
            existing_result = cursor.fetchone()

            if existing_result:
                parse_result_id = existing_result[0]
                # Update existing parse result (only content-related fields)
                cursor.execute("""
                    UPDATE parse_results
                    SET url = ?, content = ?, created_time = ?, parser = ?, 
                        state = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (entity.url, entity.content, entity.created_time, 
                      entity.parser, entity.state, parse_result_id))

                # Clear old media associations
                cursor.execute("DELETE FROM parse_result_media WHERE parse_result_id = ?", 
                             (parse_result_id,))
            else:
                # Insert new parse result
                cursor.execute("""
                    INSERT INTO parse_results
                    (pid, url, content, author_id, platform_id, user_id, created_time, parser, state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (entity.pid, entity.url, entity.content, author_id, platform_id,
                      user_id, entity.created_time, entity.parser, entity.state))
                parse_result_id = cursor.lastrowid if cursor.lastrowid else 0

            # Save media (common for both insert and update)
            self._save_media_associations(cursor, parse_result_id, entity.media)

            # Commit all changes
            conn.commit()

            return parse_result_id
        except sqlite3.Error as e:
            conn.rollback()
            raise Exception(f"Failed to save parse result (pid: {entity.pid}, platform: {entity.platform.code}): {e}")
        except Exception as e:
            conn.rollback()
            raise Exception(f"Unexpected error saving parse result: {e}")


    def _save_media_associations(self, cursor: sqlite3.Cursor, parse_result_id: int, 
                                 media: list[MediaEntity]) -> None:
        """
        Helper method to save media associations for a parse result.
        
        Args:
            cursor: Database cursor
            parse_result_id: Parse result ID
            media: List of media entities
        """
        # Save media
        media_ids = self.save_medias(media, commit=False)
        for media_id in media_ids:
            cursor.execute("""
                INSERT INTO parse_result_media (parse_result_id, media_id)
                VALUES (?, ?)
            """, (parse_result_id, media_id))


    def get_parse_result(self, parse_result_id: int) -> ParseResultEntity:
        """
        Get parse result entity by ID (internal method).
        Returns ParseResultEntity object.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT pr.*, 
                   a.id as author_id, a.uid, a.name as author_name, a.username, a.avatar, a.url as author_url,
                   a.created_at as author_created_at, a.updated_at as author_updated_at,
                   p.id as platform_id, p.code, p.name as platform_name, p.url as platform_url, p.icon_url,
                   p.created_at as platform_created_at, p.updated_at as platform_updated_at
            FROM parse_results pr
            LEFT JOIN authors a ON pr.author_id = a.id
            LEFT JOIN platforms p ON pr.platform_id = p.id
            WHERE pr.id = ?
        """, (parse_result_id,))

        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Parse result with id {parse_result_id} not found")

        # Get media
        cursor.execute("""
            SELECT m.id, m.url, m.type, m.title, m.duration, m.width, m.height, m.cover, 
                   m.media_path, m.cover_path, m.created_at
            FROM media m
            JOIN parse_result_media prm ON m.id = prm.media_id
            WHERE prm.parse_result_id = ?
        """, (parse_result_id,))

        media_rows = cursor.fetchall()
        media = [MediaEntity(
            id=m["id"],
            url=m["url"],
            type=m["type"],
            title=m["title"],
            duration=m["duration"],
            width=m["width"],
            height=m["height"],
            cover=m["cover"],
            media_path=m["media_path"],
            cover_path=m["cover_path"],
            created_at=m["created_at"]
        ) for m in media_rows]

        platform = PlatformEntity(
                id=row["platform_id"],
                code=row["code"],
                name=row["platform_name"],
                url=row["platform_url"],
                icon_url=row["icon_url"],
                created_at=row["platform_created_at"],
                updated_at=row["platform_updated_at"]
        )

        author = AuthorEntity(
                id=row["author_id"],
                platform_id=row["platform_id"],
                uid=row["uid"],
                name=row["author_name"],
                username=row["username"],
                avatar=row["avatar"],
                url=row["author_url"],
                created_at=row["author_created_at"],
                updated_at=row["author_updated_at"],
                platform=platform
        )

        # Build entity
        entity = ParseResultEntity(
            id=row["id"],
            pid=row["pid"],
            url=row["url"],
            content=row["content"],
            author_id=row["author_id"],
            platform_id=row["platform_id"],
            user_id=row["user_id"],
            created_time=row["created_time"],
            parser=row["parser"],
            state=row["state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            author=author,
            platform=platform,
            media=media
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
        conn = self._get_connection()
        cursor = conn.cursor()

        # Build WHERE clause
        where_clauses = []
        params = []

        where_clauses.append("pr.user_id = ?")
        params.append(user_id)

        if platform_id is not None:
            where_clauses.append("pr.platform_id = ?")
            params.append(platform_id)

        if author_id is not None:
            where_clauses.append("pr.author_id = ?")
            params.append(author_id)

        where_clause = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Get total count
        count_query = f"SELECT COUNT(*) FROM parse_results pr{where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        # Validate and sanitize sort parameters
        allowed_sort_fields = {
            "id": "pr.id",
            "created_time": "pr.created_time",
            "created_at": "pr.created_at",
            "updated_at": "pr.updated_at"
        }
        sort_field = allowed_sort_fields.get(sort_by, "pr.created_at")
        sort_order = "ASC" if order.lower() == "asc" else "DESC"

        # Build query with all necessary JOINs
        query = f"""
            SELECT pr.*, 
                   a.id as author_id, a.uid, a.name as author_name, a.username, a.avatar, a.url as author_url,
                   a.created_at as author_created_at, a.updated_at as author_updated_at,
                   p.id as platform_id, p.code, p.name as platform_name, p.url as platform_url, p.icon_url,
                   p.created_at as platform_created_at, p.updated_at as platform_updated_at
            FROM parse_results pr
            LEFT JOIN authors a ON pr.author_id = a.id
            LEFT JOIN platforms p ON pr.platform_id = p.id
            {where_clause}
            ORDER BY {sort_field} {sort_order}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return [], total

        # Get all parse_result_ids
        parse_result_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(parse_result_ids))

        # Batch query all media for these results
        cursor.execute(f"""
            SELECT prm.parse_result_id, m.id, m.url, m.type, m.title, m.duration, 
                   m.width, m.height, m.cover, m.media_path, m.cover_path, m.created_at
            FROM media m
            JOIN parse_result_media prm ON m.id = prm.media_id
            WHERE prm.parse_result_id IN ({placeholders})
        """, parse_result_ids)

        # Group media by parse_result_id
        media_dict = {}
        for media_row in cursor.fetchall():
            pr_id = media_row["parse_result_id"]
            if pr_id not in media_dict:
                media_dict[pr_id] = []

            media_entity = MediaEntity(
                id=media_row["id"],
                url=media_row["url"],
                type=media_row["type"],
                title=media_row["title"],
                duration=media_row["duration"],
                width=media_row["width"],
                height=media_row["height"],
                cover=media_row["cover"],
                media_path=media_row["media_path"],
                cover_path=media_row["cover_path"],
                created_at=media_row["created_at"]
            )
            media_dict[pr_id].append(media_entity)

        # Build entities and convert to models
        results = []
        for row in rows:
            pr_id = row["id"]
            media = media_dict.get(pr_id, [])
            platform = PlatformEntity(
                id=row["platform_id"],
                code=row["code"],
                name=row["platform_name"],
                url=row["platform_url"],
                icon_url=row["icon_url"],
                created_at=row["platform_created_at"],
                updated_at=row["platform_updated_at"]
            )
            author = AuthorEntity(
                id=row["author_id"],
                platform_id=row["platform_id"],
                uid=row["uid"],
                name=row["author_name"],
                username=row["username"],
                avatar=row["avatar"],
                url=row["author_url"],
                created_at=row["author_created_at"],
                updated_at=row["author_updated_at"],
                platform=platform
            )
            entity = ParseResultEntity(
                id=row["id"],
                pid=row["pid"],
                url=row["url"],
                content=row["content"],
                author_id=row["author_id"],
                platform_id=row["platform_id"],
                user_id=row["user_id"],
                created_time=row["created_time"],
                parser=row["parser"],
                state=row["state"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                author=author,
                platform=platform,
                media=media
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
        conn = self._get_connection()
        cursor = conn.cursor()

        # Get total count
        cursor.execute("SELECT COUNT(*) FROM platforms WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]

        # Validate and sanitize sort parameters
        allowed_sort_fields = {"id": "id", "name": "name", "created_at": "created_at", "updated_at": "updated_at"}
        sort_field = allowed_sort_fields.get(sort_by, "id")
        sort_order = "ASC" if order.lower() == "asc" else "DESC"

        query = f"""
            SELECT id, code, name, url, icon_url, created_at, updated_at 
            FROM platforms 
            WHERE user_id = ?
            ORDER BY {sort_field} {sort_order}
            LIMIT ? OFFSET ?
        """
        cursor.execute(query, [user_id, limit, offset])
        rows = cursor.fetchall()

        platforms = []
        for row in rows:
            platforms.append(PlatformEntity(
                id=row["id"],
                code=row["code"],
                name=row["name"],
                url=row["url"],
                icon_url=row["icon_url"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            ))

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
        conn = self._get_connection()
        cursor = conn.cursor()

        # Build WHERE clause
        where_clauses = []
        params = [] 

        where_clauses.append("a.user_id = ?")
        params.append(user_id)

        if platform_id is not None:
            where_clauses.append("a.platform_id = ?")
            params.append(platform_id)

        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        # Get total count
        count_query = f"SELECT COUNT(*) FROM authors a {where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

        # Validate and sanitize sort parameters
        allowed_sort_fields = {"id": "a.id", "name": "a.name", "created_at": "a.created_at", "updated_at": "a.updated_at"}
        sort_field = allowed_sort_fields.get(sort_by, "a.id")
        sort_order = "ASC" if order.lower() == "asc" else "DESC"

        query = f"""
            SELECT a.id, a.platform_id, a.uid, a.name, a.username, a.avatar, a.url, 
                   a.created_at, a.updated_at,
                   p.id as p_id, p.code, p.name as p_name, p.url as p_url, p.icon_url,
                   p.created_at as p_created_at, p.updated_at as p_updated_at
            FROM authors a
            LEFT JOIN platforms p ON a.platform_id = p.id
            {where_clause}
            ORDER BY {sort_field} {sort_order}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        cursor.execute(query, params)
        rows = cursor.fetchall()

        authors = []
        for row in rows:
            authors.append(AuthorEntity(
                id=row["id"],
                platform_id=row["platform_id"],
                uid=row["uid"],
                name=row["name"],
                username=row["username"],
                avatar=row["avatar"],
                url=row["url"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                platform=PlatformEntity(
                    id=row["p_id"],
                    code=row["code"],
                    name=row["p_name"],
                    url=row["p_url"],
                    icon_url=row["icon_url"],
                    created_at=row["p_created_at"],
                    updated_at=row["p_updated_at"]
                )
            ))

        return authors, total


    def delete_platform(self, user_id: int, platform_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Delete platform by ID and cascade delete related authors and parse results.
        
        Args:
            user_id: User ID performing the deletion
            platform_id: Platform ID to delete
            commit: Whether to commit immediately (default: False)
            
        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        all_file_paths = []
        
        try:
            # First verify ownership/existence of platform
            cursor.execute("""
                SELECT id FROM platforms 
                WHERE id = ? AND user_id = ?
            """, (platform_id, user_id))
            
            if not cursor.fetchone():
                logger.warning(f"Platform {platform_id} not found or access denied for user {user_id}")
                return False, all_file_paths
            
            # Get all authors belonging to this platform
            cursor.execute("SELECT id FROM authors WHERE user_id = ? AND platform_id = ?", (user_id, platform_id))
            author_ids = [row[0] for row in cursor.fetchall()]
            
            logger.info(f"Deleting platform {platform_id} with {len(author_ids)} authors")
            
            # Delete each author (which will collect file paths)
            for author_id in author_ids:
                success, file_paths = self.delete_author(user_id, author_id, commit=False)
                all_file_paths.extend(file_paths)
            
            # Delete platform
            cursor.execute("DELETE FROM platforms WHERE user_id = ? AND id = ?", (user_id, platform_id))
            
            if cursor.rowcount == 0:
                logger.warning(f"Platform {platform_id} not found for deletion")
                return False, all_file_paths  # Platform not found
            
            if commit:
                conn.commit()
                logger.info(f"Successfully deleted platform {platform_id} from database")
            
            return True, all_file_paths
            
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            logger.error(f"Database error when deleting platform {platform_id}: {e}")
            raise Exception(f"Failed to delete platform: {e}")
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Unexpected error when deleting platform {platform_id}: {e}")
            raise


    def delete_author(self, user_id: int, author_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Delete author by ID and cascade delete related parse results.
        
        Args:
            user_id: User ID performing the deletion
            author_id: Author ID to delete
            commit: Whether to commit immediately (default: False)
            
        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        all_file_paths = []
        
        try:
            # First verify ownership/existence of author
            cursor.execute("""
                SELECT id FROM authors 
                WHERE id = ? AND user_id = ?
            """, (author_id, user_id))
            
            if not cursor.fetchone():
                logger.warning(f"Author {author_id} not found or access denied for user {user_id}")
                return False, all_file_paths
            
            # Get all parse result IDs for this author
            cursor.execute("SELECT id FROM parse_results WHERE user_id = ? AND author_id = ?", (user_id, author_id))
            parse_result_ids = [row[0] for row in cursor.fetchall()]
            
            logger.info(f"Deleting author {author_id} with {len(parse_result_ids)} parse results")

            # Delete each parse result (which will collect file paths)
            for pr_id in parse_result_ids:
                success, file_paths = self.delete_parse_result(user_id, pr_id, commit=False)
                all_file_paths.extend(file_paths)

            # Delete author
            cursor.execute("DELETE FROM authors WHERE user_id = ? AND id = ?", (user_id, author_id))
            
            if cursor.rowcount == 0:
                logger.warning(f"Author {author_id} not found for deletion")
                return False, all_file_paths  # Author not found
            
            if commit:
                conn.commit()
                logger.info(f"Successfully deleted author {author_id} from database")
            
            return True, all_file_paths
            
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            logger.error(f"Database error when deleting author {author_id}: {e}")
            raise Exception(f"Failed to delete author: {e}")
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Unexpected error when deleting author {author_id}: {e}")
            raise


    def delete_parse_result(self, user_id: int, parse_result_id: int, commit: bool = False) -> tuple[bool, list[str]]:
        """
        Delete parse result by ID and return list of associated media file paths.

        Args:
            user_id: User ID performing the deletion
            parse_result_id: Parse result ID to delete
            commit: Whether to commit immediately (default: False)

        Returns:
            Tuple of (success, list of media file paths to delete)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        
        file_paths = []

        try:
            # 1. FIRST verify ownership/existence of parse result
            cursor.execute("""
                SELECT id FROM parse_results 
                WHERE id = ? AND user_id = ?
            """, (parse_result_id, user_id))
            
            if not cursor.fetchone():
                logger.warning(f"Parse result {parse_result_id} not found or access denied for user {user_id}")
                raise ValueError(f"Parse result {parse_result_id} not found or access denied")
            
            # 2. Get orphaned media IDs (only used by this parse result)
            cursor.execute("""
                SELECT media_id 
                FROM parse_result_media 
                WHERE media_id IN (
                    SELECT media_id 
                    FROM parse_result_media 
                    WHERE parse_result_id = ?
                )
                GROUP BY media_id
                HAVING COUNT(DISTINCT parse_result_id) = 1
            """, (parse_result_id,))
            
            orphaned_media_ids = [row["media_id"] for row in cursor.fetchall()]

            # 3. Collect media paths ONLY for orphaned media
            if orphaned_media_ids:
                placeholders = ",".join("?" * len(orphaned_media_ids))
                cursor.execute(f"""
                    SELECT media_path, cover_path
                    FROM media
                    WHERE id IN ({placeholders})
                """, orphaned_media_ids)
                
                for row in cursor.fetchall():
                    if row["media_path"]:
                        file_paths.append(row["media_path"])
                    if row["cover_path"]:
                        file_paths.append(row["cover_path"])

            # 4. Delete database records
            cursor.execute("DELETE FROM parse_result_media WHERE parse_result_id = ?", 
                         (parse_result_id,))

            if orphaned_media_ids:
                placeholders = ",".join("?" * len(orphaned_media_ids))
                cursor.execute(f"DELETE FROM media WHERE id IN ({placeholders})", 
                             orphaned_media_ids)
                logger.debug(f"Deleted {len(orphaned_media_ids)} orphaned media records")

            cursor.execute("DELETE FROM parse_results WHERE user_id = ? AND id = ?", (user_id, parse_result_id))
            
            # This should never fail now since we verified ownership above
            if cursor.rowcount == 0:
                logger.error(f"Unexpected: Parse result {parse_result_id} vanished during deletion")
                raise ValueError(f"Parse result {parse_result_id} unexpectedly not found")
            
            # 5. Commit if requested
            if commit:
                conn.commit()
                logger.info(f"Deleted parse result {parse_result_id} from database")

            return True, file_paths

        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            logger.error(f"Database error when deleting parse result {parse_result_id}: {e}")
            raise Exception(f"Failed to delete parse result: {e}")
        except Exception as e:
            if commit:
                conn.rollback()
            logger.error(f"Unexpected error when deleting parse result {parse_result_id}: {e}")
            raise