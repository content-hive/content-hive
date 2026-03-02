
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, BackgroundTasks

from contenthive.models.api import APIResponse, DetailedHTTPException, ErrorDetail
from contenthive.models.task import TaskCreateRequest
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_active_user
from contenthive.services.task import task_service
from contenthive.models.enumerates import TaskRole, TaskStatus

router_v1 = APIRouter(prefix="/v1/task", tags=["task"])

@router_v1.post("/parser", response_model=APIResponse)
async def create_parser_task(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    request: TaskCreateRequest,
    background_tasks: BackgroundTasks
) -> APIResponse:
    """
    Create a new parser task for parsing content from a URL.
    
    This endpoint:
    1. Creates a task with deduplication logic
    2. If it's a PRIMARY task, executes it immediately in the background
    3. If it's a LINKED task, it will be completed when the primary finishes
    4. If it's a REUSED task, it's already completed with historical data
    
    Args:
        current_user: The currently authenticated user
        request: Task creation request containing URL and optional plugin ID
        background_tasks: FastAPI background tasks executor

    Returns:
        API response with created parser task details
    """
    try:
        result = await task_service.create_parser_task(
            user_id=current_user.id,
            url=request.url,
            plugin_id=request.plugin_id
        )
        
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="TASK_CREATION_FAILED",
                message=str(e)
            )
        )
    

@router_v1.get("/parser/{task_id}", response_model=APIResponse)
async def get_parser_task(
    task_id: str,
    current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse:
    """
    Get parser task details by task ID.
    
    Args:
        task_id: Task ID string (e.g., task_abc123)
        current_user: The currently authenticated user

    Returns:
        API response with task details
    """
    try:
        task = task_service.get_main_task_by_task_id(task_id, include_sub_tasks=True)
        
        if not task:
            raise DetailedHTTPException(
                status_code=404,
                detail=ErrorDetail(
                    code="TASK_NOT_FOUND",
                    message=f"Task {task_id} not found"
                )
            )
        
        # Check if user owns this task
        if task.user_id != current_user.id:
            raise DetailedHTTPException(
                status_code=403,
                detail=ErrorDetail(
                    code="ACCESS_DENIED",
                    message="You don't have permission to access this task"
                )
            )
        
        return APIResponse(
            status="success",
            data=task
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="TASK_QUERY_FAILED",
                message=str(e)
            )
        )


@router_v1.get("/parser", response_model=APIResponse)
async def list_parser_tasks(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    status: Optional[TaskStatus] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    order: str = "desc"
) -> APIResponse:
    """
    List parser tasks for the current user with optional status filter and pagination.
    
    Args:
        current_user: The currently authenticated user
        status: Optional task status filter (e.g., pending, running, completed)
        page: Page number (starting from 1)
        page_size: Number of items per page (default: 20)
        sort_by: Field to sort by (default: created_at)
        order: Sort order - asc or desc (default: desc)
        
    Returns:
        API response with paginated list of tasks
    """
    try:
        result = task_service.list_main_tasks_by_user(
            user_id=current_user.id,
            status=status,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order
        )
        
        return APIResponse(
            status="success",
            data=result
        )
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(
                code="TASK_LIST_FAILED",
                message=str(e)
            )
        )