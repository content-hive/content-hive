
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from contenthive.config import settings
from contenthive.database.userDAO import UserDAO
from contenthive.models.api import APIResponse, ErrorDetail, DetailedHTTPException
from contenthive.models.user import LoginRequestModel, LoginResponseModel, UserModel
from contenthive.services.token import token_service
from contenthive.services.user import user_service
from contenthive.utils.user import UserUtils

router_v1 = APIRouter(prefix="/v1/user", tags=["User"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="v1/user/token")

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = DetailedHTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=ErrorDetail(
            code="INVALID_CREDENTIALS",
            message="Could not validate credentials"
        ),
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        playload = UserUtils.decode_token(
            token=token,
            secret_key=settings.secret_key,
            algorithms=[settings.algorithm]
        )
        username: Optional[str] = playload.get("sub")
        user_id: Optional[int] = playload.get("user_id")
        token_version: Optional[int] = playload.get("token_version")
    
        if username is None or user_id is None or token_version is None:
            raise credentials_exception
        
        with UserDAO() as dao:
            user = dao.get_user_by_username(username)
            if not user or user.username != username or user.token_version > token_version:
                raise credentials_exception
            
            return UserModel.from_entity(user)
    except Exception:
        raise credentials_exception
    
async def get_current_active_user(current_user: Annotated[UserModel, Depends(get_current_user)]):
    if current_user.status != 1: # active
        raise DetailedHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(
                code="INACTIVE_USER",
                message="User account is not active"
            )
        )
    return current_user

@router_v1.post("/token")
async def token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """"""
    response = await login(
        request,
        LoginRequestModel(
            username=form_data.username,
            password=form_data.password,
            client_id=form_data.client_id,
            client_secret=form_data.client_secret
        )
    )
    if isinstance(response.data, LoginResponseModel):
        return {
            "access_token": response.data.tokens.access_token,
            "token_type": response.data.tokens.token_type
        }
    else:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="TOKEN_RESPONSE_ERROR",
                message="Invalid token response format"
            )
        )


@router_v1.post("/login")
async def login(request: Request, data: LoginRequestModel) -> APIResponse:
    """"""
    try:
        result = token_service.authenticate_user(
            username=data.username,
            password=data.password,
            request=request
        )
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorDetail(
                code="AUTHENTICATION_FAILED",
                message=str(e)
            )
        )

@router_v1.post("/profile")
async def read_users_me(current_user: Annotated[UserModel, Depends(get_current_active_user)]) -> APIResponse:
    """"""
    try:
        user_profile = user_service.get_user_profile(current_user.id)
        return APIResponse(
            status="success",
            data=user_profile
        )
    except DetailedHTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="USER_PROFILE_ERROR",
                message=str(e)
            )
        )
    
@router_v1.post("/change-password")
async def change_password(current_user: Annotated[UserModel, Depends(get_current_active_user)], new_password: str) -> APIResponse:
    """"""
    try:
        user_service.change_user_password(current_user.id, new_password)
        return APIResponse(
            status="success",
            data={"message": "Password changed successfully"}
        )
    except DetailedHTTPException as http_exc:
        raise http_exc
    except Exception as e:
        raise DetailedHTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ErrorDetail(
                code="CHANGE_PASSWORD_ERROR",
                message=str(e)
            )
        )