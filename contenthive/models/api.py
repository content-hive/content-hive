from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, Any, Literal


class ErrorDetail(BaseModel):
    """Error detail model"""
    
    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[dict[str, Any]] = Field(None, description="Detailed error information")


class APIResponse(BaseModel):
    """API response model"""
    
    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Optional[Any] = Field(default=None, description="Response data")
    error: Optional[ErrorDetail] = Field(default=None, description="Error information")
    timestamp: datetime = Field(default_factory=datetime.now, description="Response timestamp")

