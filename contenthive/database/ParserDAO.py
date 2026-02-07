import sqlite3
from typing import Optional, List
from contenthive.database.db import get_db_connection
from contenthive.models.entities import ParseResultEntity, AuthorEntity, PlatformEntity, MediaEntity
from contenthive.models.mappers import ContentMapper
from contenthive.models.content import URLParserResult


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

    def save_platform(self, platform: PlatformEntity, commit: bool = False) -> int:
        """
        Save or update platform information.

        Args:
            platform: Platform entity
            commit: Whether to commit immediately (default: False)

        Returns platform_id.
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()

            # Check if platform exists
            cursor.execute("SELECT id FROM platforms WHERE code = ?", (platform.code,))
            result = cursor.fetchone()

            if result:
                # Update existing platform
                cursor.execute("""
                    UPDATE platforms
                    SET name = ?, url = ?, icon_url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                """, (platform.name, platform.url, platform.icon_url, platform.code))
                platform_id = result[0]
            else:
                # Insert new platform
                cursor.execute("""
                    INSERT INTO platforms (code, name, url, icon_url)
                    VALUES (?, ?, ?, ?)
                """, (platform.code, platform.name, platform.url, platform.icon_url))
                platform_id = cursor.lastrowid

            if commit:
                conn.commit()

            return platform_id
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            raise Exception(f"Failed to save platform: {e}")


    def save_author(self, author: AuthorEntity, platform_id: int, commit: bool = False) -> int:
        """
        Save or update author information.

        Args:
            author: Author entity
            platform_id: Platform ID
            commit: Whether to commit immediately (default: False)

        Returns author_id.
        """
        conn = self._get_connection()

        try:
            cursor = conn.cursor()

            # Check if author exists
            cursor.execute(
                "SELECT id FROM authors WHERE platform_id = ? AND uid = ?",
                (platform_id, author.uid)
            )
            result = cursor.fetchone()

            if result:
                # Update existing author
                cursor.execute("""
                    UPDATE authors
                    SET name = ?, username = ?, avatar = ?, url = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE platform_id = ? AND uid = ?
                """, (author.name, author.username, author.avatar, author.url, platform_id, author.uid))
                author_id = result[0]
            else:
                # Insert new author
                cursor.execute("""
                    INSERT INTO authors (platform_id, uid, name, username, avatar, url)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (platform_id, author.uid, author.name, author.username, author.avatar, author.url))
                author_id = cursor.lastrowid

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
                return result[0]

            # Insert new media
            cursor.execute("""
                INSERT INTO media (url, type)
                VALUES (?, ?)
            """, (media.url, media.type))

            media_id = cursor.lastrowid

            if commit:
                conn.commit()

            return media_id
        except sqlite3.Error as e:
            if commit:
                conn.rollback()
            raise Exception(f"Failed to save media: {e}")


    def save_parse_result(self, result: URLParserResult, user_id: Optional[int] = None) -> Optional[URLParserResult]:
        """
        Save complete parse result including platform, author, and media.
        Uses a single transaction for all operations.

        Returns the saved URLParserResult from database.
        """
        # Convert model to entity
        entity = ContentMapper.model_to_entity(result, user_id)
        
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Save platform and author first
            platform_id = self.save_platform(entity.platform, commit=False)
            author_id = self.save_author(entity.author, platform_id, commit=False)

            # Check if parse result already exists using pid and platform code
            cursor.execute("""
                SELECT pr.id 
                FROM parse_results pr
                JOIN platforms p ON pr.platform_id = p.id
                WHERE pr.pid = ? AND p.code = ?
            """, (entity.pid, entity.platform.code))
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
                parse_result_id = cursor.lastrowid

            # Save media (common for both insert and update)
            self._save_media_associations(cursor, parse_result_id, entity.images, entity.videos)

            # Commit all changes
            conn.commit()

            # Get saved entity from database and convert to model
            saved_entity = self._get_parse_result_entity(parse_result_id)
            return ContentMapper.entity_to_model(saved_entity)

        except sqlite3.Error as e:
            conn.rollback()
            raise Exception(f"Failed to save parse result (pid: {entity.pid}, platform: {entity.platform.code}): {e}")
        except Exception as e:
            conn.rollback()
            raise Exception(f"Unexpected error saving parse result: {e}")


    def _save_media_associations(self, cursor: sqlite3.Cursor, parse_result_id: int, 
                                 images: List[MediaEntity], videos: List[MediaEntity]) -> None:
        """
        Helper method to save media associations for a parse result.
        
        Args:
            cursor: Database cursor
            parse_result_id: Parse result ID
            images: List of image entities
            videos: List of video entities
        """
        # Save images
        for image in images:
            media_id = self.save_media(image, commit=False)
            cursor.execute("""
                INSERT INTO parse_result_media (parse_result_id, media_id)
                VALUES (?, ?)
            """, (parse_result_id, media_id))

        # Save videos
        for video in videos:
            media_id = self.save_media(video, commit=False)
            cursor.execute("""
                INSERT INTO parse_result_media (parse_result_id, media_id)
                VALUES (?, ?)
            """, (parse_result_id, media_id))


    def _get_parse_result_entity(self, parse_result_id: int) -> ParseResultEntity:
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
            SELECT m.id, m.url, m.type, m.created_at
            FROM media m
            JOIN parse_result_media prm ON m.id = prm.media_id
            WHERE prm.parse_result_id = ?
        """, (parse_result_id,))

        media_rows = cursor.fetchall()
        images = [MediaEntity(
            id=m["id"],
            url=m["url"],
            type=m["type"],
            created_at=m["created_at"]
        ) for m in media_rows if m["type"] == "image"]
        
        videos = [MediaEntity(
            id=m["id"],
            url=m["url"],
            type=m["type"],
            created_at=m["created_at"]
        ) for m in media_rows if m["type"] == "video"]

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
            author=AuthorEntity(
                id=row["author_id"],
                platform_id=row["platform_id"],
                uid=row["uid"],
                name=row["author_name"],
                username=row["username"],
                avatar=row["avatar"],
                url=row["author_url"],
                created_at=row["author_created_at"],
                updated_at=row["author_updated_at"]
            ),
            platform=PlatformEntity(
                id=row["platform_id"],
                code=row["code"],
                name=row["platform_name"],
                url=row["platform_url"],
                icon_url=row["icon_url"],
                created_at=row["platform_created_at"],
                updated_at=row["platform_updated_at"]
            ),
            images=images,
            videos=videos
        )

        return entity


    def get_parse_result(self, parse_result_id: int) -> Optional[URLParserResult]:
        """
        Get parse result by ID.
        Returns URLParserResult object or None if not found.
        """
        try:
            entity = self._get_parse_result_entity(parse_result_id)
            return ContentMapper.entity_to_model(entity)
        except ValueError:
            return None


    def list_parse_results(self, user_id: Optional[int] = None,
                          platform_id: Optional[int] = None,
                          author_id: Optional[int] = None,
                          limit: int = 20, offset: int = 0) -> List[URLParserResult]:
        """
        List parse results with pagination.

        Args:
            user_id: Filter by user ID
            platform_id: Filter by platform ID
            author_id: Filter by author ID
            limit: Maximum number of results to return
            offset: Number of results to skip

        Returns list of URLParserResult objects.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Build query with all necessary JOINs
        query = """
            SELECT pr.*, 
                   a.id as author_id, a.uid, a.name as author_name, a.username, a.avatar, a.url as author_url,
                   a.created_at as author_created_at, a.updated_at as author_updated_at,
                   p.id as platform_id, p.code, p.name as platform_name, p.url as platform_url, p.icon_url,
                   p.created_at as platform_created_at, p.updated_at as platform_updated_at
            FROM parse_results pr
            LEFT JOIN authors a ON pr.author_id = a.id
            LEFT JOIN platforms p ON pr.platform_id = p.id
        """

        # Build WHERE clause
        where_clauses = []
        params = []

        if user_id is not None:
            where_clauses.append("pr.user_id = ?")
            params.append(user_id)

        if platform_id is not None:
            where_clauses.append("pr.platform_id = ?")
            params.append(platform_id)

        if author_id is not None:
            where_clauses.append("pr.author_id = ?")
            params.append(author_id)

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY pr.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()

        if not rows:
            return []

        # Get all parse_result_ids
        parse_result_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" * len(parse_result_ids))

        # Batch query all media for these results
        cursor.execute(f"""
            SELECT prm.parse_result_id, m.id, m.url, m.type, m.created_at
            FROM media m
            JOIN parse_result_media prm ON m.id = prm.media_id
            WHERE prm.parse_result_id IN ({placeholders})
        """, parse_result_ids)

        # Group media by parse_result_id
        media_dict = {}
        for media_row in cursor.fetchall():
            pr_id = media_row["parse_result_id"]
            if pr_id not in media_dict:
                media_dict[pr_id] = {"images": [], "videos": []}

            media_entity = MediaEntity(
                id=media_row["id"],
                url=media_row["url"],
                type=media_row["type"],
                created_at=media_row["created_at"]
            )

            if media_row["type"] == "image":
                media_dict[pr_id]["images"].append(media_entity)
            else:
                media_dict[pr_id]["videos"].append(media_entity)

        # Build entities and convert to models
        results = []
        for row in rows:
            pr_id = row["id"]
            media = media_dict.get(pr_id, {"images": [], "videos": []})

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
                author=AuthorEntity(
                    id=row["author_id"],
                    platform_id=row["platform_id"],
                    uid=row["uid"],
                    name=row["author_name"],
                    username=row["username"],
                    avatar=row["avatar"],
                    url=row["author_url"],
                    created_at=row["author_created_at"],
                    updated_at=row["author_updated_at"]
                ),
                platform=PlatformEntity(
                    id=row["platform_id"],
                    code=row["code"],
                    name=row["platform_name"],
                    url=row["platform_url"],
                    icon_url=row["icon_url"],
                    created_at=row["platform_created_at"],
                    updated_at=row["platform_updated_at"]
                ),
                images=media["images"],
                videos=media["videos"]
            )

            results.append(ContentMapper.entity_to_model(entity))

        return results


    def delete_parse_result(self, parse_result_id: int) -> bool:
        """
        Delete parse result by ID.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM parse_results WHERE id = ?", (parse_result_id,))
        conn.commit()

        return cursor.rowcount > 0


    def list_platforms(self) -> List[PlatformEntity]:
        """
        List all platforms.
        Returns list of PlatformEntity objects.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, code, name, url, icon_url, created_at, updated_at FROM platforms")
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

        return platforms


    def list_authors(self, platform_id: Optional[int] = None) -> List[AuthorEntity]:
        """
        List authors, optionally filtered by platform_id.
        Returns list of AuthorEntity objects.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if platform_id:
            cursor.execute("""
                SELECT id, platform_id, uid, name, username, avatar, url, created_at, updated_at
                FROM authors
                WHERE platform_id = ?
            """, (platform_id,))
        else:
            cursor.execute("""
                SELECT id, platform_id, uid, name, username, avatar, url, created_at, updated_at
                FROM authors
            """)

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
                updated_at=row["updated_at"]
            ))

        return authors


parserDAO = ParserDAO()