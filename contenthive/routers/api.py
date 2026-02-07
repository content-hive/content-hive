from typing import Optional
from fastapi import APIRouter
from pydantic import HttpUrl
from contenthive.models.content import APIResponse, ErrorDetail
from contenthive.services.parser import parserService

router_v1 = APIRouter(prefix="/v1")

@router_v1.get("/parser", response_model=APIResponse)
async def parser_url(url: HttpUrl, plugin_id: Optional[str] = None) -> APIResponse:
    try:
        result = await parserService.parser_content(url, plugin_id=plugin_id)
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="1234",
                message="Failed to fetch URL content",
                details=None
            )
        )
    

@router_v1.get("/contents", response_model=APIResponse)
async def list_contents(platform_id: Optional[int] = None, author_id: Optional[int] = None) -> APIResponse:
    try:
        result = await parserService.list_contents(platform_id=platform_id, author_id=author_id)
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="5678",
                message="Failed to fetch contents from the database",
                details=None
            )
        )
    

@router_v1.get("/platforms", response_model=APIResponse)
async def list_platforms() -> APIResponse:
    try:
        platforms = await parserService.list_platforms()
        return APIResponse(
            status="success",
            data=platforms
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="9101",
                message="Failed to fetch platforms from the database",
                details=None
            )
        )
    

@router_v1.get("/authors", response_model=APIResponse)
async def list_authors(platform_id: Optional[int] = None) -> APIResponse:
    try:
        authors = await parserService.list_authors(platform_id=platform_id)
        return APIResponse(
            status="success",
            data=authors
        )
    except Exception as e:
        return APIResponse(
            status="error",
            error=ErrorDetail(
                code="1121",
                message="Failed to fetch authors from the database",
                details=None
            )
        )