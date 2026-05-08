from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from contenthive.core.secret import secret_manager
from contenthive.database.user_dao import UserDAO
from contenthive.models.api import (
    APIResponse,
    DetailedHTTPException,
    ErrorDetail,
    OperationResult,
)
from contenthive.models.enumerates import OperationType, ResponseStatus, UserStatus
from contenthive.models.user import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    UserModel,
    UserProfileResponse,
)
from contenthive.services.token import token_service
from contenthive.services.user import user_service

router_v1 = APIRouter(prefix="/v1/user", tags=["user"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/user/token")


async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = DetailedHTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ErrorDetail(
            code="INVALID_CREDENTIALS", message="Could not validate credentials"
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = secret_manager.decode_token(token=token)
        username: str | None = payload.get("sub")
        user_id: int | None = payload.get("user_id")
        token_version: int | None = payload.get("token_version")

        if username is None or user_id is None or token_version is None:
            raise credentials_exception

        with UserDAO() as dao:
            user = dao.get_user_by_username(username)
            if (
                not user
                or user.username != username
                or user.token_version != token_version
            ):
                raise credentials_exception

            return UserModel.from_entity(user)
    except Exception:
        raise credentials_exception


async def get_current_active_user(
    current_user: Annotated[UserModel, Depends(get_current_user)],
):
    if current_user.status != UserStatus.ACTIVE:
        raise DetailedHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(
                code="INACTIVE_USER", message="User account is not active"
            ),
        )
    return current_user


async def get_current_admin_user(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
):
    if not current_user.is_admin:
        raise DetailedHTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorDetail(
                code="ADMIN_PRIVILEGES_REQUIRED",
                message="Admin privileges are required to access this resource",
            ),
        )
    return current_user


@router_v1.post("/token")
async def token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """"""
    response = await login(
        request,
        LoginRequest(
            username=form_data.username,
            password=form_data.password,
            client_id=form_data.client_id,
            client_secret=form_data.client_secret,
        ),
    )
    if isinstance(response.data, LoginResponse):
        return {
            "access_token": response.data.tokens.access_token,
            "token_type": response.data.tokens.token_type,
        }
    else:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="TOKEN_RESPONSE_ERROR", message="Invalid token response format"
            ),
        )


@router_v1.post("/login", response_model=APIResponse[LoginResponse])
async def login(request: Request, data: LoginRequest) -> APIResponse[LoginResponse]:
    """"""
    try:
        result = token_service.authenticate_user(
            username=data.username, password=data.password, request=request
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(code="AUTHENTICATION_FAILED", message=str(e)),
        )


@router_v1.post("/refresh-token", response_model=APIResponse[RefreshTokenResponse])
async def refresh_token(
    request: Request, data: RefreshTokenRequest
) -> APIResponse[RefreshTokenResponse]:
    """"""
    try:
        result = token_service.refresh_access_token(
            refresh_token=data.refresh_token, request=request
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(code="TOKEN_REFRESH_FAILED", message=str(e)),
        )


@router_v1.get("/profile", response_model=APIResponse[UserProfileResponse])
async def read_users_me(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[UserProfileResponse]:
    """"""
    try:
        user_profile = user_service.get_user_profile(current_user.id)
        return APIResponse(status=ResponseStatus.SUCCESS, data=user_profile)
    except DetailedHTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="USER_PROFILE_ERROR", message=str(e)),
        )


@router_v1.post("/change-password", response_model=APIResponse[OperationResult])
async def change_password(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    data: ChangePasswordRequest,
) -> APIResponse[OperationResult]:
    """"""
    try:
        user_service.change_user_password(current_user.id, data.new_password)
        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.UPDATE,
                id=str(current_user.id),
                success=True,
                message="Password changed successfully",
            ),
        )
    except DetailedHTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(code="CHANGE_PASSWORD_ERROR", message=str(e)),
        )
