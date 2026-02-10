from typing import Optional
from fastapi import APIRouter
from pydantic import HttpUrl
from contenthive.models.content import APIResponse, ErrorDetail
from contenthive.services.parser import parserService

router_v1 = APIRouter(prefix="/v1")

@router_v1.get("/parser", response_model=APIResponse, tags=["Parser"])
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
                code="PARSER_ERROR",
                message="Failed to parse URL content",
                details=str(e)
            )
        )
    

@router_v1.get("/contents", response_model=APIResponse, tags=["Content"])
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
                code="CONTENTS_FETCH_ERROR",
                message="Failed to fetch contents from the database",
                details=str(e)
            )
        )
    

@router_v1.get("/platforms", response_model=APIResponse, tags=["Platform"])
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
                code="PLATFORMS_FETCH_ERROR",
                message="Failed to fetch platforms from the database",
                details=str(e)
            )
        )
    

@router_v1.get("/authors", response_model=APIResponse, tags=["Author"])
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
                code="AUTHORS_FETCH_ERROR",
                message="Failed to fetch authors from the database",
                details=str(e)
            )
        )


@router_v1.delete("/platforms/{platform_id}", response_model=APIResponse, tags=["Platform"])
async def delete_platform(platform_id: int) -> APIResponse:
    try:
        success = await parserService.delete_platform(platform_id)
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
                details=str(e)
            )
        )


@router_v1.delete("/authors/{author_id}", response_model=APIResponse, tags=["Author"])
async def delete_author(author_id: int) -> APIResponse:
    try:
        success = await parserService.delete_author(author_id)
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
                details=str(e)
            )
        )


@router_v1.delete("/contents/{parse_result_id}", response_model=APIResponse, tags=["Content"])
async def delete_content(parse_result_id: int) -> APIResponse:
    try:
        success = await parserService.delete_parse_result(parse_result_id)
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
                details=str(e)
            )
        )