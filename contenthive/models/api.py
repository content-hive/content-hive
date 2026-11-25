from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from contenthive.models.enumerates import OperationType, ResponseStatus

# ERROR CODE CONSTANTS


class APIBaseModel(BaseModel):
    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


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
    details: dict[str, Any] | None = Field(default=None, description="Detailed error information")


class APIResponse[T](APIBaseModel):
    """API response model"""

    status: ResponseStatus = Field(..., description="Response status")
    data: T | None = Field(default=None, description="Response data")
    error: ErrorDetail | None = Field(default=None, description="Error information")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Response timestamp",
    )


class DetailedHTTPException(HTTPException):
    """Custom exception for detailed HTTP errors"""

    def __init__(
        self,
        status_code: int,
        detail: ErrorDetail,
        headers: dict[str, str] | None = None,
    ):
        response = APIResponse(status=ResponseStatus.ERROR, error=detail)
        super().__init__(
            status_code=status_code,
            detail=response.model_dump(mode="json"),
            headers=headers,
        )


class RequestValidationFailure(APIBaseModel):
    """One request validation failure. `loc` is for clients; `message` is for display."""

    loc: list[str | int] = Field(..., description="Where the invalid value was found")
    message: str = Field(..., description="Validation message")


def _request_validation_failures(exc: RequestValidationError) -> list[RequestValidationFailure]:
    """Collect validation failures without echoing submitted input."""
    failures: list[RequestValidationFailure] = []
    for err in exc.errors():
        message = str(err.get("msg", ""))
        if not message:
            continue
        loc = [part if isinstance(part, int) else str(part) for part in (err.get("loc") or ())]
        failures.append(RequestValidationFailure(loc=loc, message=message))
    return failures


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return request validation failures in the standard API error envelope."""
    failures = _request_validation_failures(exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=APIResponse(
            status=ResponseStatus.ERROR,
            error=ErrorDetail(
                code="REQUEST_VALIDATION_FAILED",
                message="; ".join(failure.message for failure in failures),
                details={"errors": [failure.model_dump() for failure in failures]},
            ),
        ).model_dump(mode="json"),
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, DetailedHTTPException):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    else:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=APIResponse(
                status=ResponseStatus.ERROR,
                error=ErrorDetail(
                    code="INTERNAL_SERVER_ERROR",
                    message="An unexpected error occurred",
                    details={"error": str(exc)},
                ),
            ).model_dump(mode="json"),
        )
