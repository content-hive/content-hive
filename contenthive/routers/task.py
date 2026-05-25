from typing import Annotated

from fastapi import APIRouter, Depends, Query

from contenthive.models.api import (
    APIResponse,
    DetailedHTTPException,
    ErrorDetail,
    OperationResult,
)
from contenthive.models.content import PaginatedResponse
from contenthive.models.enumerates import OperationType, ResponseStatus, TaskStatus
from contenthive.models.system import CursorPaginatedResponse
from contenthive.models.task import MainTaskInfo, TaskCreateRequest
from contenthive.models.user import UserModel
from contenthive.routers.user import get_current_active_user
from contenthive.services.task import task_service

router_v1 = APIRouter(prefix="/v1/task", tags=["task"])


@router_v1.post("/parser", response_model=APIResponse[MainTaskInfo])
async def create_parser_task(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    request: TaskCreateRequest,
) -> APIResponse[MainTaskInfo]:
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
    Returns:
        API response with created parser task details
    """
    try:
        result = await task_service.create_parser_task(
            user_id=current_user.id, url=request.url, plugin_id=request.plugin_id
        )

        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(code="TASK_CREATION_FAILED", message=str(e)),
        ) from e


@router_v1.delete("/parser/{task_id}", response_model=APIResponse[OperationResult])
async def cancel_parser_task(
    task_id: str, current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse[OperationResult]:
    """
    Cancel a parser task by task ID.

    Only the task owner can cancel it. Tasks that are already completed, failed,
    or canceled cannot be cancelled again.

    Args:
        task_id: Task ID string (e.g., task_abc123)
        current_user: The currently authenticated user

    Returns:
        API response confirming cancellation
    """
    try:
        task = task_service.get_main_task_by_task_id(task_id)

        if not task:
            raise DetailedHTTPException(
                status_code=404,
                detail=ErrorDetail(code="TASK_NOT_FOUND", message=f"Task {task_id} not found"),
            )

        if task.user_id != current_user.id:
            raise DetailedHTTPException(
                status_code=403,
                detail=ErrorDetail(
                    code="ACCESS_DENIED",
                    message="You don't have permission to cancel this task",
                ),
            )

        success = await task_service.cancel_main_task(task.id)
        if not success:
            raise DetailedHTTPException(
                status_code=409,
                detail=ErrorDetail(
                    code="TASK_CANCEL_FAILED",
                    message=f"Task {task_id} cannot be cancelled in its current state",
                ),
            )

        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=OperationResult(
                operation=OperationType.CANCEL,
                id=task_id,
                success=True,
                message=f"Task {task_id} has been canceled",
            ),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(code="TASK_CANCEL_FAILED", message=str(e)),
        ) from e


@router_v1.get("/parser/cursor", response_model=APIResponse[CursorPaginatedResponse[MainTaskInfo]])
async def list_parser_tasks_with_cursor(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    status: list[TaskStatus] | None = Query(None),
    task_ids: list[str] | None = Query(None),
    cursor: str | None = Query(None, description="Pagination cursor from previous response; omit for first page"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("created_at", pattern="^(id|created_at|updated_at)$", description="Sort field"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order"),
    include_sub_tasks: bool = Query(False, description="Whether to include sub tasks in the response"),
) -> APIResponse[CursorPaginatedResponse[MainTaskInfo]]:
    """
    List parser tasks using cursor-based (keyset) pagination.

    Pass next_cursor from the previous response to fetch the next page.
    A null next_cursor means there are no more pages.
    """
    try:
        result = task_service.list_main_tasks_by_user_with_cursor(
            user_id=current_user.id,
            status=status,
            task_ids=task_ids,
            cursor=cursor,
            limit=limit,
            sort_by=sort_by,
            order=order,
            include_sub_tasks=include_sub_tasks,
        )
        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except ValueError as e:
        raise DetailedHTTPException(
            status_code=400,
            detail=ErrorDetail(code="INVALID_CURSOR", message=str(e)),
        ) from e
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(code="TASK_LIST_FAILED", message=str(e)),
        ) from e


@router_v1.get("/parser/{task_id}", response_model=APIResponse[MainTaskInfo])
async def get_parser_task(
    task_id: str, current_user: Annotated[UserModel, Depends(get_current_active_user)]
) -> APIResponse[MainTaskInfo]:
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
                detail=ErrorDetail(code="TASK_NOT_FOUND", message=f"Task {task_id} not found"),
            )

        # Check if user owns this task
        if task.user_id != current_user.id:
            raise DetailedHTTPException(
                status_code=403,
                detail=ErrorDetail(
                    code="ACCESS_DENIED",
                    message="You don't have permission to access this task",
                ),
            )

        return APIResponse(
            status=ResponseStatus.SUCCESS,
            data=MainTaskInfo.from_entity(task, include_sub_tasks=True),
        )
    except DetailedHTTPException:
        raise
    except Exception as e:
        raise DetailedHTTPException(
            status_code=500,
            detail=ErrorDetail(code="TASK_QUERY_FAILED", message=str(e)),
        ) from e


@router_v1.get("/parser", response_model=APIResponse[PaginatedResponse[MainTaskInfo]])
async def list_parser_tasks(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    status: list[TaskStatus] | None = Query(None),
    task_ids: list[str] | None = Query(None),
    page: int = Query(1, ge=1, description="Page number (starting from 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (1-100)"),
    sort_by: str = Query("created_at", pattern="^(id|created_at|updated_at)$", description="Sort field"),
    order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order"),
    include_sub_tasks: bool = Query(False, description="Whether to include sub tasks in the response"),
) -> APIResponse[PaginatedResponse[MainTaskInfo]]:
    """
    List parser tasks for the current user with optional status filter and pagination.

    Args:
        current_user: The currently authenticated user
        status: Optional task status filter (e.g., pending, running, completed). Ignored when task_ids is provided.
        task_ids: Optional list of task IDs to filter by. When provided, status filter is ignored.
        page: Page number (starting from 1)
        page_size: Number of items per page (default: 20)
        sort_by: Field to sort by (default: created_at)
        order: Sort order - asc or desc (default: desc)
        include_sub_tasks: Whether to include sub tasks in the response (default: false)

    Returns:
        API response with paginated list of tasks
    """
    try:
        result = task_service.list_main_tasks_by_user(
            user_id=current_user.id,
            status=status,
            task_ids=task_ids,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            order=order,
            include_sub_tasks=include_sub_tasks,
        )

        return APIResponse(status=ResponseStatus.SUCCESS, data=result)
    except Exception as e:
        raise DetailedHTTPException(status_code=500, detail=ErrorDetail(code="TASK_LIST_FAILED", message=str(e))) from e
