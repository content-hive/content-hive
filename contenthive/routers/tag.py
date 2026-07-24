"""Tag vocabulary and assignment API routes."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from contenthive.models.api import (
    APIResponse,
    DetailedHTTPException,
    ErrorDetail,
    OperationResult,
)
from contenthive.models.content import PaginatedResponse, SyncResponse
from contenthive.models.enumerates import OperationType, ResponseStatus, TagEffect
from contenthive.models.tag import (
    CreateTagRequest,
    ReplaceTagEffectsRequest,
    SyncTagInfo,
    TagAssignmentRequest,
    TagEffectInfo,
    TagInfo,
    UpdateTagRequest,
    UpsertTagEffectRequest,
)
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_active_user
from contenthive.services.tag import tag_service

router_v1 = APIRouter(prefix="/v1/tags", tags=["tags"])


@router_v1.get("/sync", response_model=APIResponse[SyncResponse[SyncTagInfo]])
async def sync_tags(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    last_sync_at: datetime | None = Query(
        None,
        description="Last sync timestamp in ISO 8601 format (e.g., 2026-02-25T12:00:00Z)",
    ),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
) -> APIResponse[SyncResponse[SyncTagInfo]]:
    try:
        result = await tag_service.sync_tags(
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
                code="TAGS_SYNC_ERROR",
                message="Failed to sync tags",
                details={"error": str(e)},
            ),
        )


@router_v1.get("", response_model=APIResponse[PaginatedResponse[TagInfo]])
async def list_tags(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("name", pattern="^(name|created_at|updated_at)$", description="Sort field"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order"),
) -> APIResponse[PaginatedResponse[TagInfo]]:
    try:
        result = await tag_service.list_tags(
            user_id=current_user.id,
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
                code="TAGS_FETCH_ERROR",
                message="Failed to fetch tags",
                details={"error": str(e)},
            ),
        )


@router_v1.post("", response_model=APIResponse[TagInfo], status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: CreateTagRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[TagInfo]:
    try:
        tag = await tag_service.create_tag(current_user.id, body.name)
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


@router_v1.put("/assignments", response_model=APIResponse[list[TagInfo]])
async def replace_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await tag_service.assign_tags(
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


@router_v1.post("/assignments", response_model=APIResponse[list[TagInfo]])
async def add_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await tag_service.assign_tags(
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


@router_v1.delete("/assignments", response_model=APIResponse[list[TagInfo]])
async def remove_tag_assignment(
    body: TagAssignmentRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagInfo]]:
    try:
        tags = await tag_service.assign_tags(
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


@router_v1.get("/effects", response_model=APIResponse[list[TagEffectInfo]])
async def list_tag_effects(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagEffectInfo]]:
    try:
        effects = await tag_service.list_tag_effects(current_user.id)
        return APIResponse(status=ResponseStatus.SUCCESS, data=effects)
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_EFFECTS_FETCH_ERROR",
                message="Failed to fetch tag effects",
                details={"error": str(e)},
            ),
        )


@router_v1.put("/effects", response_model=APIResponse[list[TagEffectInfo]])
async def replace_tag_effects(
    body: ReplaceTagEffectsRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[list[TagEffectInfo]]:
    try:
        items = [(item.tag_id, item.effect) for item in body.items]
        effects = await tag_service.replace_tag_effects(current_user.id, items)
        if effects is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(
                    code="TAG_NOT_FOUND",
                    message="One or more tags were not found",
                ),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=effects)
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_EFFECTS_REPLACE_ERROR",
                message="Failed to replace tag effects",
                details={"error": str(e)},
            ),
        )


@router_v1.put("/effects/{tag_id}", response_model=APIResponse[TagEffectInfo])
async def upsert_tag_effect(
    tag_id: int,
    body: UpsertTagEffectRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[TagEffectInfo]:
    try:
        effect = await tag_service.upsert_tag_effect(current_user.id, tag_id, body.effect)
        if effect is None:
            raise DetailedHTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorDetail(code="TAG_NOT_FOUND", message=f"Tag {tag_id} not found"),
            )
        return APIResponse(status=ResponseStatus.SUCCESS, data=effect)
    except DetailedHTTPException:
        raise
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_EFFECT_UPSERT_ERROR",
                message="Failed to upsert tag effect",
                details={"error": str(e)},
            ),
        )


@router_v1.delete("/effects/{tag_id}", response_model=APIResponse[OperationResult])
async def delete_tag_effect(
    tag_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    effect: TagEffect | None = Query(
        None,
        description="Effect to remove; omit to clear all effects for this tag",
    ),
) -> APIResponse[OperationResult]:
    try:
        await tag_service.delete_tag_effect(current_user.id, tag_id, effect=effect)
        message = (
            f"Tag effect {effect.value} for {tag_id} cleared"
            if effect is not None
            else f"All tag effects for {tag_id} cleared"
        )
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.DELETE,
                id=str(tag_id),
                success=True,
                message=message,
            ),
        )
    except Exception as e:
        return APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="TAG_EFFECT_DELETE_ERROR",
                message="Failed to delete tag effect",
                details={"error": str(e)},
            ),
        )


@router_v1.patch("/{tag_id}", response_model=APIResponse[TagInfo])
async def rename_tag(
    tag_id: int,
    body: UpdateTagRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[TagInfo]:
    try:
        tag = await tag_service.rename_tag(current_user.id, tag_id, body.name)
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


@router_v1.delete("/{tag_id}", response_model=APIResponse[OperationResult])
async def delete_tag(
    tag_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[OperationResult]:
    try:
        success = await tag_service.delete_tag(current_user.id, tag_id)
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
