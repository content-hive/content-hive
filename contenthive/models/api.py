from datetime import datetime
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any, Literal

# ERROR CODE CONSTANTS



class BaseEntity(BaseModel):
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

class ErrorDetail(BaseEntity):
    """Error detail model"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[dict[str, Any]] = Field(default=None, description="Detailed error information")


class APIResponse(BaseEntity):
    """API response model"""
    
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[Any] = Field(default=None, description="Response data")
    error: Optional[ErrorDetail] = Field(default=None, description="Error information")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")

class DetailedHTTPException(HTTPException):
    """Custom exception for detailed HTTP errors"""
    
    def __init__(self, status_code: int, detail: ErrorDetail, headers: Optional[dict[str, str]] = None):
        response = APIResponse(
            status="error",
            error=detail
        )
        super().__init__(
            status_code=status_code,
            detail=response.model_dump(mode="json"),
            headers=headers
        )

async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, DetailedHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=APIResponse(
                status="error",
                error=ErrorDetail(
                    code="INTERNAL_SERVER_ERROR",
                    message="An unexpected error occurred",
                    details={"error": str(exc)}
                )
            ).model_dump(mode="json")
        )