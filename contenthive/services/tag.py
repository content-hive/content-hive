"""Tag service for vocabulary CRUD, assignments, and sync."""

from datetime import UTC, datetime

from contenthive.database.tag_dao import TagDAO
from contenthive.logger import logger
from contenthive.models.content import PaginatedResponse, PaginationInfo, SyncResponse
from contenthive.models.tag import SyncTagInfo, TagInfo


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
        """List tags in the user's vocabulary with pagination and sorting."""
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
        """Create a tag in the user's vocabulary without attaching it to content."""
        try:
            with TagDAO() as dao:
                tag = dao.create_tag(user_id, name, commit=True)
            return TagInfo.from_entity(tag)
        except Exception:
            logger.exception(f"Error creating tag for user {user_id}")
            raise

    async def rename_tag(self, user_id: int, tag_id: int, name: str) -> TagInfo | None:
        """Rename a tag in the user's vocabulary."""
        try:
            with TagDAO() as dao:
                tag = dao.rename_tag(user_id, tag_id, name, commit=True)
            return TagInfo.from_entity(tag) if tag else None
        except Exception:
            logger.exception(f"Error renaming tag {tag_id} for user {user_id}")
            raise

    async def delete_tag(self, user_id: int, tag_id: int) -> bool:
        """Delete a tag and remove it from all of the user's associations."""
        try:
            with TagDAO() as dao:
                return dao.delete_tag(user_id, tag_id, commit=True)
        except Exception:
            logger.exception(f"Error deleting tag {tag_id} for user {user_id}")
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
        """Assign tags to content, media, or author."""
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
        """Incrementally sync tag vocabulary for the user."""
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
