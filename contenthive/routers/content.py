from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from contenthive.models.api import (
    APIResponse,
    DetailedHTTPException,
    ErrorDetail,
    OperationResult,
)
from contenthive.models.content import (
    AuthorInfo,
    CreateTagRequest,
    PaginatedResponse,
    PlatformInfo,
    SyncResponse,
    TagAssignmentRequest,
    TagInfo,
    UpdateTagRequest,
    URLParserResult,
)
from contenthive.models.enumerates import OperationType, ResponseStatus
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_active_user
from contenthive.services.content import content_service

router_v1 = APIRouter(prefix="/v1/content", tags=["content"])


@router_v1.get("/contents", response_model=APIResponse[PaginatedResponse[URLParserResult]])
async def list_contents(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    platform_id: int | None = Query(None, description="Filter by platform ID"),
    author_id: int | None = Query(None, description="Filter by author ID"),
    tag_id: int | None = Query(None, description="Only include contents with this tag ID"),
    exclude_tag_id: int | None = Query(None, description="Exclude contents with this tag ID"),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query(
        "created_at",
        pattern="^(id|post_time|created_at|updated_at)$",
        description="Sort field",
    ),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order"),
) -> APIResponse[PaginatedResponse[URLParserResult]]:
    try:
        result = await content_service.list_contents(
            user_id=current_user.id,
            platform_id=platform_id,
            author_id=author_id,
            tag_id=tag_id,
            exclude_tag_id=exclude_tag_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order,
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="CONTENTS_FETCH_ERROR",
                message="Failed to fetch contents from the database",
                details={"error": str(e)},
            ),
        )


@router_v1.get("/tags", response_model=APIResponse[list[TagInfo]])
async def list_tags(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await content_service.list_tags(current_user.id)
        return APIResponse(status=ResponseStatus.SUCCESS, data=tags)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAGS_FETCH_ERROR",
                message="Failed to fetch tags",
                details={"error": str(e)},
            ),
        )


@router_v1.post("/tags", response_model=APIResponse[TagInfo], status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: CreateTagRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[TagInfo]:
    try:
        tag = await content_service.create_tag(current_user.id, body.name)
        return APIResponse(status=ResponseStatus.SUCCESS, data=tag)
    except ValueError as e:
        message = str(e)
        if "already exists" in message:
            raise DetailedHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorDetail(code="TAG_ALREADY_EXISTS", message=message),
            ) from e
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(code="TAG_INVALID_NAME", message=message),
        ) from e
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_CREATE_ERROR",
                message="Failed to create tag",
                details={"error": str(e)},
            ),
        )


@router_v1.patch("/tags/{tag_id}", response_model=APIResponse[TagInfo])
async def rename_tag(
    tag_id: int,
    body: UpdateTagRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[TagInfo]:
    try:
        tag = await content_service.rename_tag(current_user.id, tag_id, body.name)
        if tag is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(code="TAG_NOT_FOUND", message=f"Tag {tag_id} not found"),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=tag)
    except DetailedHTTPException:
        raise
    except ValueError as e:
        message = str(e)
        if "already exists" in message:
            raise DetailedHTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ErrorDetail(code="TAG_ALREADY_EXISTS", message=message),
            ) from e
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(code="TAG_INVALID_NAME", message=message),
        ) from e
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_UPDATE_ERROR",
                message="Failed to rename tag",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/tags/{tag_id}", response_model=APIResponse[OperationResult])
async def delete_tag(
    tag_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[OperationResult]:
    try:
        success = await content_service.delete_tag(current_user.id, tag_id)
        if not success:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(code="TAG_NOT_FOUND", message=f"Tag {tag_id} not found"),
            )
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.DELETE,
                id=str(tag_id),
                success=True,
                message=f"Tag {tag_id} deleted successfully",
            ),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_DELETE_ERROR",
                message="Failed to delete tag",
                details={"error": str(e)},
            ),
        )


@router_v1.put("/tag-assignments", response_model=APIResponse[list[TagInfo]])
async def replace_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await content_service.assign_tags(
            user_id=current_user.id,
            target=body.target,
            target_id=body.id,
            mode="replace",
            names=body.names,
        )
        if tags is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code=f"{body.target.upper()}_NOT_FOUND",
                    message=f"{body.target.capitalize()} {body.id} not found",
                ),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=tags)
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_ASSIGNMENT_REPLACE_ERROR",
                message="Failed to replace tag assignment",
                details={"error": str(e)},
            ),
        )


@router_v1.post("/tag-assignments", response_model=APIResponse[list[TagInfo]])
async def add_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await content_service.assign_tags(
            user_id=current_user.id,
            target=body.target,
            target_id=body.id,
            mode="add",
            names=body.names,
        )
        if tags is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code=f"{body.target.upper()}_NOT_FOUND",
                    message=f"{body.target.capitalize()} {body.id} not found",
                ),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=tags)
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_ASSIGNMENT_ADD_ERROR",
                message="Failed to add tag assignment",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/tag-assignments", response_model=APIResponse[list[TagInfo]])
async def remove_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await content_service.assign_tags(
            user_id=current_user.id,
            target=body.target,
            target_id=body.id,
            mode="remove",
            names=body.names,
            tag_ids=body.tag_ids,
        )
        if tags is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code=f"{body.target.upper()}_NOT_FOUND",
                    message=f"{body.target.capitalize()} {body.id} not found",
                ),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=tags)
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_ASSIGNMENT_REMOVE_ERROR",
                message="Failed to remove tag assignment",
                details={"error": str(e)},
            ),
        )


@router_v1.get("/platforms", response_model=APIResponse[PaginatedResponse[PlatformInfo]])
async def list_platforms(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("id", pattern="^(id|name|created_at|updated_at)$", description="Sort field"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
) -> APIResponse[PaginatedResponse[PlatformInfo]]:
    try:
        platforms = await content_service.list_platforms(
            user_id=current_user.id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order,
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=platforms)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="PLATFORMS_FETCH_ERROR",
                message="Failed to fetch platforms from the database",
                details={"error": str(e)},
            ),
        )


@router_v1.get("/authors", response_model=APIResponse[PaginatedResponse[AuthorInfo]])
async def list_authors(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    platform_id: int | None = Query(None, description="Filter by platform ID"),
    tag_id: int | None = Query(None, description="Only include authors with this tag ID"),
    exclude_tag_id: int | None = Query(None, description="Exclude authors with this tag ID"),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("id", pattern="^(id|name|created_at|updated_at)$", description="Sort field"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
) -> APIResponse[PaginatedResponse[AuthorInfo]]:
    try:
        authors = await content_service.list_authors(
            user_id=current_user.id,
            platform_id=platform_id,
            tag_id=tag_id,
            exclude_tag_id=exclude_tag_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order,
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=authors)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="AUTHORS_FETCH_ERROR",
                message="Failed to fetch authors from the database",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/platforms/{platform_id}", response_model=APIResponse[OperationResult])
async def delete_platform(
    platform_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[OperationResult]:
    try:
        success = await content_service.delete_platform(current_user.id, platform_id)
        if not success:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code="PLATFORM_NOT_FOUND",
                    message=f"Platform {platform_id} not found",
                ),
            )
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.DELETE,
                id=str(platform_id),
                success=success,
                message=f"Platform {platform_id} deleted successfully",
            ),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="PLATFORM_DELETE_ERROR",
                message="Failed to delete platform",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/authors/{author_id}", response_model=APIResponse[OperationResult])
async def delete_author(
    author_id: int, current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse[OperationResult]:
    try:
        success = await content_service.delete_author(current_user.id, author_id)
        if not success:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(code="AUTHOR_NOT_FOUND", message=f"Author {author_id} not found"),
            )
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.DELETE,
                id=str(author_id),
                success=success,
                message=f"Author {author_id} deleted successfully",
            ),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="AUTHOR_DELETE_ERROR",
                message="Failed to delete author",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/contents/{parse_result_id}", response_model=APIResponse[OperationResult])
async def delete_content(
    parse_result_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[OperationResult]:
    try:
        success = await content_service.delete_parse_result(current_user.id, parse_result_id)
        if not success:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code="CONTENT_NOT_FOUND",
                    message=f"Content {parse_result_id} not found",
                ),
            )
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.DELETE,
                id=str(parse_result_id),
                success=success,
                message=f"Content {parse_result_id} deleted successfully",
            ),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="CONTENT_DELETE_ERROR",
                message="Failed to delete content",
                details={"error": str(e)},
            ),
        )


@router_v1.get("/sync", response_model=APIResponse[SyncResponse[URLParserResult]])
async def increment_sync(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    last_sync_at: datetime | None = Query(
        None,
        description="Last sync timestamp in ISO 8601 format (e.g., 2026-02-25T12:00:00Z)",
    ),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
) -> APIResponse[SyncResponse[URLParserResult]]:
    try:
        result = await content_service.increment_sync(
            user_id=current_user.id,
            last_sync_time=last_sync_at,
            page=page,
            page_size=page_size,
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="CONTENT_SYNC_ERROR",
                message="Failed to sync content with external platforms",
                details={"error": str(e)},
            ),
        )
