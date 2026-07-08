from fastapi import APIRouter, Body, Request, status

from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.enumerates import ResponseStatus
from contenthive.models.setup import SetupAdminRequest
from contenthive.models.user import LoginResponse
from contenthive.services.setup import setup_service

router_v1 = APIRouter(prefix="/v1/setup", tags=["setup"])


@router_v1.post("", response_model=APIResponse[LoginResponse])
async def complete_setup(
    request: Request,
    body: SetupAdminRequest = Body(...),
) -> APIResponse[LoginResponse]:
    """Create the first admin user and return login tokens."""
    try:
        data = await setup_service.complete_setup(body, request)
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(code="SETUP_FAILED", message=str(e)),
        ) from e
    return APIResponse(status=ResponseStatus.SUCCESS, data=data)
