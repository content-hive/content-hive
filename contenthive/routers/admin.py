
from typing import Annotated
from fastapi import APIRouter, Depends, status

from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.user import CreateUserRequest, UserModel, UserStatusUpdateRequest
from contenthive.routers.user import get_current_admin_user
from contenthive.services.user import user_service

router_v1 = APIRouter(prefix="/v1/admin", tags=["admin"])

@router_v1.post("/users")
async def create_user(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)],
    user_request: CreateUserRequest
) -> APIResponse:
    """
    Create a new user (Admin only)
    """
    try:
        user = user_service.create_user(
            created_by=current_user.id,
            username=user_request.username,
            password=user_request.password,
            email=user_request.email,
            is_admin=user_request.is_admin
        )
        return APIResponse(
            status="success",
            data=user
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="USER_CREATION_FAILED",
                message=str(e)
            )
        )
    
@router_v1.get("/users")
async def list_users(
    current_user: Annotated[UserModel, Depends(get_current_admin_user)]
) -> APIResponse:
    """
    List all users (Admin only)
    """
    try:
        users = user_service.list_users()
        return APIResponse(
            status="success",
            data=users
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="USER_LISTING_FAILED",
                message=str(e)
            )
        )
    
@router_v1.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)]
) -> APIResponse:
    """
    Reset a user's password (Admin only)
    """
    if user_id == current_user.id:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="CANNOT_RESET_OWN_PASSWORD",
                message="Admins cannot reset their own password via this endpoint"
            )
        )
    try:
        new_password = user_service.reset_user_password(user_id)
        return APIResponse(
            status="success",
            data={"new_password": new_password}
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="PASSWORD_RESET_FAILED",
                message=str(e)
            )
        )
    
@router_v1.patch("/users/{user_id}/status")
async def change_user_status(
    user_id: int,
    user_status: UserStatusUpdateRequest,
    current_user: Annotated[UserModel, Depends(get_current_admin_user)]
) -> APIResponse:
    """
    Change a user's active status (Admin only)
    """
    if user_id == current_user.id:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="CANNOT_CHANGE_OWN_STATUS",
                message="Admins cannot change their own status"
            )
        )
    try:
        result = user_service.change_user_status(user_id, user_status.status)
        return APIResponse(
            status="success",
            data={"status_changed": result}
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorDetail(
                code="USER_STATUS_CHANGE_FAILED",
                message=str(e)
            )
        )