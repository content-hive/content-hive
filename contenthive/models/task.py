"""
Models for task-related operations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import Field

from contenthive.database.orm_models import MainTask, SubTask
from contenthive.models.api import APIBaseModel
from contenthive.models.enumerates import TaskType, TaskStatus, TaskRole


# Database Models

@dataclass
class MainTaskEntity:
    """Main task database entity"""
    id: int
    task_id: str
    user_id: int
    type: TaskType
    status: TaskStatus
    url: str
    role: Optional[TaskRole] = field(default=None)
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = field(default=None)
    error_message: Optional[str] = field(default=None)
    started_at: Optional[datetime] = field(default=None)
    completed_at: Optional[datetime] = field(default=None)
    primary_task_id: Optional[int] = field(default=None)
    parse_result_id: Optional[int] = field(default=None)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)
    deleted_at: Optional[datetime] = field(default=None)
    
    # Related entities (for joins)
    sub_tasks: List["SubTaskEntity"] = field(default_factory=list)
    
    @classmethod
    def from_orm(cls, orm: MainTask) -> "MainTaskEntity":
        """
        Convert ORM MainTask object to MainTaskEntity.
        
        Args:
            orm: SQLAlchemy MainTask ORM object
            
        Returns:
            MainTaskEntity dataclass instance
        """
        sub_tasks = []
        if hasattr(orm, 'sub_tasks') and orm.sub_tasks:
            sub_tasks = [SubTaskEntity.from_orm(st) for st in orm.sub_tasks]

        return cls(
            id=orm.id,
            task_id=orm.task_id,
            user_id=orm.user_id,
            type=orm.type,
            status=orm.status,
            url=orm.url,
            role=orm.role,
            parameters=orm.parameters,
            result=orm.result,
            error_message=orm.error_message,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            primary_task_id=orm.primary_task_id,
            parse_result_id=orm.parse_result_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at,
            sub_tasks=sub_tasks
        )


@dataclass
class SubTaskEntity:
    """Sub task database entity"""
    id: int
    sub_task_id: str
    main_task_id: int
    type: TaskType
    status: TaskStatus
    progress: int = field(default=0)
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = field(default=None)
    error_message: Optional[str] = field(default=None)
    started_at: Optional[datetime] = field(default=None)
    completed_at: Optional[datetime] = field(default=None)
    depends_on_id: Optional[int] = field(default=None)
    created_at: Optional[datetime] = field(default=None)
    updated_at: Optional[datetime] = field(default=None)
    deleted_at: Optional[datetime] = field(default=None)
    
    @classmethod
    def from_orm(cls, orm: SubTask) -> "SubTaskEntity":
        """
        Convert ORM SubTask object to SubTaskEntity.
        
        Args:
            orm: SQLAlchemy SubTask ORM object
            
        Returns:
            SubTaskEntity dataclass instance
        """
        return cls(
            id=orm.id,
            sub_task_id=orm.sub_task_id,
            main_task_id=orm.main_task_id,
            type=orm.type,
            status=orm.status,
            progress=orm.progress,
            parameters=orm.parameters,
            result=orm.result,
            error_message=orm.error_message,
            started_at=orm.started_at,
            completed_at=orm.completed_at,
            depends_on_id=orm.depends_on_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            deleted_at=orm.deleted_at
        )

# API Request Models 

class TaskCreateRequest(APIBaseModel):
    """Request model for creating a main task"""
    url: str = Field(..., description="URL to be processed")
    plugin_id: Optional[str] = Field(None, description="Optional plugin ID to use for parsing")


# API Response Models

class SubTaskInfo(APIBaseModel):
    """Sub task information response model"""
    id: int = Field(..., description="Sub task database ID")
    sub_task_id: str = Field(..., description="Unique sub task identifier")
    main_task_id: int = Field(..., description="Parent main task ID")
    type: TaskType = Field(..., description="Task type")
    status: TaskStatus = Field(..., description="Task status")
    progress: int = Field(..., description="Progress percentage (0-100)")
    parameters: Dict[str, Any] = Field(..., description="Task parameters")
    result: Optional[Dict[str, Any]] = Field(None, description="Task result")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = Field(None, description="Task start time")
    completed_at: Optional[datetime] = Field(None, description="Task completion time")
    depends_on_id: Optional[int] = Field(None, description="ID of sub task this depends on")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @classmethod
    def from_entity(cls, entity: SubTaskEntity) -> "SubTaskInfo":
        """Create SubTaskInfo from SubTaskEntity"""
        return cls(
            id=entity.id,
            sub_task_id=entity.sub_task_id,
            main_task_id=entity.main_task_id,
            type=entity.type,
            status=entity.status,
            progress=entity.progress,
            parameters=entity.parameters,
            result=entity.result,
            error_message=entity.error_message,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            depends_on_id=entity.depends_on_id,
            created_at=entity.created_at or datetime.now(),
            updated_at=entity.updated_at or datetime.now()
        )


class MainTaskInfo(APIBaseModel):
    """Main task information response model"""
    id: int = Field(..., description="Main task database ID")
    task_id: str = Field(..., description="Unique task identifier")
    user_id: int = Field(..., description="User ID who created the task")
    type: TaskType = Field(..., description="Task type")
    status: TaskStatus = Field(..., description="Task status")
    url: str = Field(..., description="Target URL for the task")
    role: Optional[TaskRole] = Field(None, description="Task role (primary, linked, reused)")
    parameters: Dict[str, Any] = Field(..., description="Task parameters")
    result: Optional[Dict[str, Any]] = Field(None, description="Task result")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = Field(None, description="Task start time")
    completed_at: Optional[datetime] = Field(None, description="Task completion time")
    primary_task_id: Optional[int] = Field(None, description="ID of primary task if this is linked/reused")
    parse_result_id: Optional[int] = Field(None, description="Associated parse result ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    sub_tasks: List[SubTaskInfo] = Field(default_factory=list, description="List of sub tasks")

    @classmethod
    def from_entity(cls, entity: MainTaskEntity, include_sub_tasks: bool = False) -> "MainTaskInfo":
        """Create MainTaskInfo from MainTaskEntity"""
        sub_tasks = []
        if include_sub_tasks and entity.sub_tasks:
            sub_tasks = [SubTaskInfo.from_entity(st) for st in entity.sub_tasks]
        
        return cls(
            id=entity.id,
            task_id=entity.task_id,
            user_id=entity.user_id,
            type=entity.type,
            status=entity.status,
            url=entity.url,
            role=entity.role,
            parameters=entity.parameters,
            result=entity.result,
            error_message=entity.error_message,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
            primary_task_id=entity.primary_task_id,
            parse_result_id=entity.parse_result_id,
            created_at=entity.created_at or datetime.now(),
            updated_at=entity.updated_at or datetime.now(),
            sub_tasks=sub_tasks
        )


class SubTaskCreateResponse(APIBaseModel):
    """Response model for sub task creation"""
    id: int = Field(..., description="Sub task database ID")
    sub_task_id: str = Field(..., description="Unique sub task identifier")
    main_task_id: int = Field(..., description="Parent main task ID")
    type: TaskType = Field(..., description="Task type")
    status: TaskStatus = Field(..., description="Task status")
    created_at: datetime = Field(..., description="Creation timestamp")

    @classmethod
    def from_entity(cls, entity: SubTaskEntity) -> "SubTaskCreateResponse":
        """Create SubTaskCreateResponse from SubTaskEntity"""
        return cls(
            id=entity.id,
            sub_task_id=entity.sub_task_id,
            main_task_id=entity.main_task_id,
            type=entity.type,
            status=entity.status,
            created_at=entity.created_at or datetime.now()
        )


class TaskExecutionResponse(APIBaseModel):
    """Response model for task execution"""
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Current task status")
    result: Optional[Dict[str, Any]] = Field(None, description="Task execution result")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = Field(None, description="Task start time")
    completed_at: Optional[datetime] = Field(None, description="Task completion time")


class TaskListQuery(APIBaseModel):
    """Query parameters for listing tasks"""
    user_id: Optional[int] = Field(None, description="Filter by user ID")
    type: Optional[TaskType] = Field(None, description="Filter by task type")
    status: Optional[TaskStatus] = Field(None, description="Filter by status")
    role: Optional[TaskRole] = Field(None, description="Filter by role")
    limit: int = Field(100, description="Maximum number of results", ge=1, le=1000)
    offset: int = Field(0, description="Offset for pagination", ge=0)
    include_sub_tasks: bool = Field(False, description="Whether to include sub tasks")


class TaskStatistics(APIBaseModel):
    """Task statistics response model"""
    total_tasks: int = Field(..., description="Total number of tasks")
    pending_tasks: int = Field(..., description="Number of pending tasks")
    running_tasks: int = Field(..., description="Number of running tasks")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    failed_tasks: int = Field(..., description="Number of failed tasks")
    canceled_tasks: int = Field(..., description="Number of canceled tasks")
    by_type: Dict[str, int] = Field(default_factory=dict, description="Task count by type")
