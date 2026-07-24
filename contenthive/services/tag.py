"""Tag service for vocabulary CRUD, assignments, effects, and sync."""

from datetime import UTC, datetime

from contenthive.database.tag_dao import TagDAO
from contenthive.logger import logger
from contenthive.models.content import PaginatedResponse, PaginationInfo, SyncResponse
from contenthive.models.enumerates import TagEffect
from contenthive.models.tag import SyncTagInfo, TagEffectInfo, TagInfo


class TagService:
    """Service layer for per-user tags."""

    async def list_tags(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        order: str = "asc",
    ) -> PaginatedResponse[TagInfo]:
        """
        List tags in the user's vocabulary with pagination and sorting.

        Args:
            user_id: User ID
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by (name, created_at, updated_at)
            order: Sort order (asc/desc)

        Returns:
            PaginatedResponse containing list of TagInfo and pagination info
        """
        try:
            offset = (page - 1) * page_size
            with TagDAO() as dao:
                tags, total = dao.list_tags(
                    user_id,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order,
                )
            items = [TagInfo.from_entity(tag) for tag in tags]
            total_pages = (total + page_size - 1) // page_size
            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(page=page, page_size=page_size, total=total, total_pages=total_pages),
            )
        except Exception:
            logger.exception(f"Error listing tags for user {user_id}")
            raise

    async def create_tag(self, user_id: int, name: str) -> TagInfo:
        """
        Create a tag in the user's vocabulary without attaching it to content.

        Args:
            user_id: User ID
            name: Tag name

        Returns:
            Created TagInfo
        """
        try:
            with TagDAO() as dao:
                tag = dao.create_tag(user_id, name, commit=True)
            return TagInfo.from_entity(tag)
        except Exception:
            logger.exception(f"Error creating tag for user {user_id}")
            raise

    async def rename_tag(self, user_id: int, tag_id: int, name: str) -> TagInfo | None:
        """
        Rename a tag in the user's vocabulary.

        Args:
            user_id: User ID
            tag_id: Tag ID
            name: New tag name

        Returns:
            Updated TagInfo, or None if not found
        """
        try:
            with TagDAO() as dao:
                tag = dao.rename_tag(user_id, tag_id, name, commit=True)
            return TagInfo.from_entity(tag) if tag else None
        except Exception:
            logger.exception(f"Error renaming tag {tag_id} for user {user_id}")
            raise

    async def delete_tag(self, user_id: int, tag_id: int) -> bool:
        """
        Delete a tag and remove it from all of the user's associations.

        Args:
            user_id: User ID
            tag_id: Tag ID

        Returns:
            True if deleted
        """
        try:
            with TagDAO() as dao:
                return dao.delete_tag(user_id, tag_id, commit=True)
        except Exception:
            logger.exception(f"Error deleting tag {tag_id} for user {user_id}")
            raise

    async def list_tag_effects(self, user_id: int) -> list[TagEffectInfo]:
        """List all tag display effects for the user."""
        try:
            with TagDAO() as dao:
                effects = dao.list_tag_effects(user_id)
            return [TagEffectInfo.from_entity(effect) for effect in effects]
        except Exception:
            logger.exception(f"Error listing tag effects for user {user_id}")
            raise

    async def upsert_tag_effect(self, user_id: int, tag_id: int, effect: TagEffect) -> TagEffectInfo | None:
        """
        Add a display effect to a tag without removing other effects.

        Returns:
            TagEffectInfo, or None if the tag is not found / not owned
        """
        try:
            with TagDAO() as dao:
                row = dao.upsert_tag_effect(user_id, tag_id, effect, commit=True)
            return TagEffectInfo.from_entity(row) if row else None
        except Exception:
            logger.exception(f"Error upserting tag effect for tag {tag_id} user {user_id}")
            raise

    async def delete_tag_effect(self, user_id: int, tag_id: int, effect: TagEffect | None = None) -> bool:
        """Remove one effect (when set) or all effects for a tag (idempotent)."""
        try:
            with TagDAO() as dao:
                return dao.delete_tag_effect(user_id, tag_id, effect=effect, commit=True)
        except Exception:
            logger.exception(f"Error deleting tag effect for tag {tag_id} user {user_id}")
            raise

    async def replace_tag_effects(self, user_id: int, items: list[tuple[int, TagEffect]]) -> list[TagEffectInfo] | None:
        """
        Replace all tag effects for the user.

        Returns:
            Resulting list, or None if any tag_id is invalid
        """
        try:
            with TagDAO() as dao:
                effects = dao.replace_tag_effects(user_id, items, commit=True)
            return [TagEffectInfo.from_entity(effect) for effect in effects] if effects is not None else None
        except Exception:
            logger.exception(f"Error replacing tag effects for user {user_id}")
            raise

    async def assign_tags(
        self,
        user_id: int,
        target: str,
        target_id: int,
        mode: str,
        names: list[str] | None = None,
        tag_ids: list[int] | None = None,
    ) -> list[TagInfo] | None:
        """
        Assign tags to content, media, or author.

        Args:
            user_id: User ID
            target: content, media, or author
            target_id: Target resource ID
            mode: replace, add, or remove
            names: Tag names
            tag_ids: Tag IDs (remove mode)

        Returns:
            Resulting tags, or None if target not found / not accessible
        """
        try:
            with TagDAO() as dao:
                tags = dao.apply_tag_assignment(
                    user_id=user_id,
                    target=target,
                    target_id=target_id,
                    mode=mode,
                    names=names,
                    tag_ids=tag_ids,
                    commit=True,
                )
            return [TagInfo.from_entity(tag) for tag in tags] if tags is not None else None
        except Exception:
            logger.exception(f"Error assigning tags to {target} {target_id} (mode={mode})")
            raise

    async def sync_tags(
        self,
        user_id: int,
        last_sync_time: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> SyncResponse[SyncTagInfo]:
        """
        Incrementally sync tag vocabulary for the user based on last sync time.

        Args:
            user_id: User ID to sync tags for
            last_sync_time: Optional datetime of the last sync. If not provided, returns all active tags.
            page: Page number (starting from 1)
            page_size: Number of items per page

        Returns:
            SyncResponse with items, pagination info, and server sync_timestamp
        """
        try:
            sync_timestamp = datetime.now(UTC)
            offset = (page - 1) * page_size
            with TagDAO() as dao:
                results, total = dao.sync_tags(
                    user_id=user_id,
                    last_sync_time=last_sync_time,
                    limit=page_size,
                    offset=offset,
                )

            items = [SyncTagInfo.from_entity(tag) for tag in results]
            total_pages = (total + page_size - 1) // page_size
            return SyncResponse(
                items=items,
                pagination=PaginationInfo(page=page, page_size=page_size, total=total, total_pages=total_pages),
                sync_timestamp=sync_timestamp,
            )
        except Exception:
            logger.exception(f"Error syncing tags for user {user_id}")
            raise


tag_service = TagService()
