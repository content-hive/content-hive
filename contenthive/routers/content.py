from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import HttpUrl
from contenthive.models.api import APIResponse, ErrorDetail
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_active_user
from contenthive.services.content import parserService

router_v1 = APIRouter(prefix="/v1/content", tags=["content"])

@router_v1.get("/parser", response_model=APIResponse)
async def parser_url(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    url: HttpUrl,
    plugin_id: Optional[str] = None
) -> APIResponse:
    try:
        result = await parserService.parser_content(current_user.id, url, plugin_id=plugin_id)
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="PARSER_ERROR",
                message="Failed to parse URL content",
                details={"error": str(e)}
            )
        )
    

@router_v1.get("/contents", response_model=APIResponse)
async def list_contents(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    platform_id: Optional[int] = Query(None, description="Filter by platform ID"),
    author_id: Optional[int] = Query(None, description="Filter by author ID"),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("created_at", pattern="^(id|created_time|created_at|updated_at)$", description="Sort field"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order")
) -> APIResponse:
    try:
        result = await parserService.list_contents(
            user_id=current_user.id,
            platform_id=platform_id,
            author_id=author_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order
        )
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="CONTENTS_FETCH_ERROR",
                message="Failed to fetch contents from the database",
                details={"error": str(e)}
            )
        )
    

@router_v1.get("/platforms", response_model=APIResponse)
async def list_platforms(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("id", pattern="^(id|name|created_at|updated_at)$", description="Sort field"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order")
) -> APIResponse:
    try:
        platforms = await parserService.list_platforms(
            user_id=current_user.id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order
        )
        return APIResponse(
            status="success",
            data=platforms
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="PLATFORMS_FETCH_ERROR",
                message="Failed to fetch platforms from the database",
                details={"error": str(e)}
            )
        )
    

@router_v1.get("/authors", response_model=APIResponse)
async def list_authors(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    platform_id: Optional[int] = Query(None, description="Filter by platform ID"),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("id", pattern="^(id|name|created_at|updated_at)$", description="Sort field"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Sort order")
) -> APIResponse:
    try:
        authors = await parserService.list_authors(
            user_id=current_user.id,
            platform_id=platform_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order
        )
        return APIResponse(
            status="success",
            data=authors
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="AUTHORS_FETCH_ERROR",
                message="Failed to fetch authors from the database",
                details={"error": str(e)}
            )
        )


@router_v1.delete("/platforms/{platform_id}", response_model=APIResponse)
async def delete_platform(
    platform_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse:
    try:
        success = await parserService.delete_platform(current_user.id, platform_id)
        return APIResponse(
            status="success",
            data={"deleted": success, "platform_id": platform_id}
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="PLATFORM_DELETE_ERROR",
                message="Failed to delete platform",
                details={"error": str(e)}
            )
        )


@router_v1.delete("/authors/{author_id}", response_model=APIResponse)
async def delete_author(
    author_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse:
    try:
        success = await parserService.delete_author(current_user.id, author_id)
        return APIResponse(
            status="success",
            data={"deleted": success, "author_id": author_id}
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="AUTHOR_DELETE_ERROR",
                message="Failed to delete author",
                details={"error": str(e)}
            )
        )


@router_v1.delete("/contents/{parse_result_id}", response_model=APIResponse)
async def delete_content(
    parse_result_id: int,
    current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse:
    try:
        success = await parserService.delete_parse_result(current_user.id, parse_result_id)
        return APIResponse(
            status="success",
            data={"deleted": success, "parse_result_id": parse_result_id}
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="CONTENT_DELETE_ERROR",
                message="Failed to delete content",
                details={"error": str(e)}
            )
        )