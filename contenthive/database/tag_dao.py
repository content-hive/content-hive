"""Data access for per-user tag vocabulary and assignments."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import (
    Media,
    Tag,
    UserAuthor,
    UserMedia,
    UserParseResult,
)
from contenthive.models.tag import TagEntity


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


class TagDAO:
    """Data Access Object for tag vocabulary and per-user tag assignments."""

    def __init__(self, session: Session | None = None):
        """
        Initialize TagDAO.

        Args:
            session: Optional shared SQLAlchemy session. When provided (e.g. from
                ContentDAO), TagDAO does not own or close the session. Prefer
                ``with TagDAO() as dao:`` or ``with TagDAO(session=...) as dao:``.
        """
        self.engine = get_engine()
        self.SessionLocal = get_session_local()
        self.session = session
        self._owns_session = session is None

    def __enter__(self):
        if self.session is None:
            self.session = self.SessionLocal()
            self._owns_session = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_session(self) -> Session:
        if self.session is None:
            self.session = self.SessionLocal()
            self._owns_session = True
        return self.session

    def close(self):
        if self.session and self._owns_session:
            self.session.close()
            self.session = None

    def list_tags(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "name",
        order: str = "asc",
    ) -> tuple[list[TagEntity], int]:
        """
        List tags in the user's vocabulary with pagination and sorting.

        Args:
            user_id: User ID
            limit: Maximum number of results to return
            offset: Number of results to skip
            sort_by: Field to sort by (name, created_at, updated_at)
            order: Sort order (asc/desc)

        Returns:
            Tuple of (TagEntity list, total count)
        """
        session = self._get_session()
        base = select(Tag).where(Tag.user_id == user_id, Tag.deleted_at.is_(None))
        total = session.execute(select(func.count()).select_from(base.subquery())).scalar()
        total = total if total is not None else 0

        sort_field_map = {
            "name": Tag.name,
            "created_at": Tag.created_at,
            "updated_at": Tag.updated_at,
        }
        sort_field = sort_field_map.get(sort_by, Tag.name)
        if order.lower() == "asc":
            stmt = base.order_by(sort_field.asc(), Tag.id.asc()).limit(limit).offset(offset)
        else:
            stmt = base.order_by(sort_field.desc(), Tag.id.desc()).limit(limit).offset(offset)
        tags = session.execute(stmt).scalars().all()
        return [TagEntity.from_orm(tag) for tag in tags], total

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
        Rename a tag in the user vocabulary (content associations are not bumped; clients sync tag names separately).

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

        return self.resolve_tags_for_ids(user_id, new_ids)

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

        return self.resolve_tags_for_ids(user_id, new_ids)

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

        return self.resolve_tags_for_ids(user_id, new_ids)

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

        return self.resolve_tags_for_ids(user_id, list(association.tags or []))

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

        return self.resolve_tags_for_ids(user_id, list(user_media.tags or []))

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

        return self.resolve_tags_for_ids(user_id, list(association.tags or []))

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

    def resolve_tags_for_ids(self, user_id: int, tag_ids: list[int]) -> list[TagEntity]:
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

    def load_media_tag_ids_map(self, user_id: int, media_ids: list[int]) -> dict[int, list[int]]:
        """Load raw per-user tag IDs keyed by media id (no tags-table lookup)."""
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
        return {row.media_id: list(dict.fromkeys(int(tid) for tid in (row.tags or []))) for row in rows}

    def load_author_tag_ids_map(self, user_id: int, author_ids: list[int]) -> dict[int, list[int]]:
        """Load raw per-user tag IDs keyed by author id (no tags-table lookup)."""
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
        return {row.author_id: list(dict.fromkeys(int(tid) for tid in (row.tags or []))) for row in rows}

    def load_media_tags_map(self, user_id: int, media_ids: list[int]) -> dict[int, list[TagEntity]]:
        """Load resolved per-user tags keyed by media id."""
        raw_by_media = self.load_media_tag_ids_map(user_id, media_ids)
        if not raw_by_media:
            return {}

        all_tag_ids = [tid for ids in raw_by_media.values() for tid in ids]
        resolved = {tag.id: tag for tag in self.resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}
        return {media_id: [resolved[tid] for tid in ids if tid in resolved] for media_id, ids in raw_by_media.items()}

    def load_user_media_updated_at(self, user_id: int, media_ids: list[int]) -> dict[int, datetime]:
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

    def load_author_tags_map(self, user_id: int, author_ids: list[int]) -> dict[int, list[TagEntity]]:
        """Load resolved per-user tags keyed by author id."""
        raw_by_author = self.load_author_tag_ids_map(user_id, author_ids)
        if not raw_by_author:
            return {}

        all_tag_ids = [tid for ids in raw_by_author.values() for tid in ids]
        resolved = {tag.id: tag for tag in self.resolve_tags_for_ids(user_id, all_tag_ids) if tag.id is not None}
        return {
            author_id: [resolved[tid] for tid in ids if tid in resolved] for author_id, ids in raw_by_author.items()
        }

    def load_user_author_updated_at(self, user_id: int, author_ids: list[int]) -> dict[int, datetime]:
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

    def sync_tags(
        self,
        user_id: int,
        last_sync_time: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[TagEntity], int]:
        """
        Sync tag vocabulary for a user.

        First sync (last_sync_time is None): active tags only.
        Incremental: rows with updated_at > last_sync_time, including soft-deleted.
        """
        session = self._get_session()
        query = select(Tag).where(Tag.user_id == user_id)
        if last_sync_time is None:
            query = query.where(Tag.deleted_at.is_(None))
        else:
            query = query.where(Tag.updated_at > last_sync_time)

        count_query = select(func.count()).select_from(query.subquery())
        total = session.execute(count_query).scalar()
        total = total if total is not None else 0

        query = query.order_by(Tag.updated_at.desc(), Tag.id.desc()).limit(limit).offset(offset)
        tags = session.execute(query).scalars().all()
        return [TagEntity.from_orm(tag) for tag in tags], total
