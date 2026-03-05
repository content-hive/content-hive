from datetime import datetime, timezone
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any, Generic, TypeVar
from contenthive.models.enumerates import OperationType, ResponseStatus

T = TypeVar("T")

# ERROR CODE CONSTANTS


class APIBaseModel(BaseModel):
    model_config = ConfigDict(
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )


class OperationResult(APIBaseModel):
    """Unified response model for write operations (delete, cancel, etc.)"""

    operation: OperationType = Field(..., description="Type of operation performed")
    id: str = Field(..., description="ID of the affected resource")
    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Human-readable result message")

class ErrorDetail(APIBaseModel):
    """Error detail model"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[dict[str, Any]] = Field(default=None, description="Detailed error information")


class APIResponse(APIBaseModel, Generic[T]):
    """API response model"""
    
    status: ResponseStatus = Field(..., description="Response status")
    data: Optional[T] = Field(default=None, description="Response data")
    error: Optional[ErrorDetail] = Field(default=None, description="Error information")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Response timestamp")

class DetailedHTTPException(HTTPException):
    """Custom exception for detailed HTTP errors"""
    
    def __init__(self, status_code: int, detail: ErrorDetail, headers: Optional[dict[str, str]] = None):
        response = APIResponse(
            status=ResponseStatus.ERROR,
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
                status=ResponseStatus.ERROR,
                error=ErrorDetail(
                    code="INTERNAL_SERVER_ERROR",
                    message="An unexpected error occurred",
                    details={"error": str(exc)}
                )
            ).model_dump(mode="json")
        )