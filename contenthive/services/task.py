"""
Task service for managing and executing tasks.
"""

import asyncio
import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from contenthive.database.content_dao import ContentDAO
from contenthive.database.task_dao import TaskDAO
from contenthive.logger import logger
from contenthive.models.content import (
    DownloadedMediaInfo,
    MediaEntity,
    PaginatedResponse,
    PaginationInfo,
)
from contenthive.models.enumerates import (
    AuthorProfileAsset,
    MediaStatus,
    SubTaskResultStatus,
    TaskRole,
    TaskStatus,
    TaskType,
)
from contenthive.models.system import CursorPaginatedResponse
from contenthive.models.task import MainTaskEntity, MainTaskInfo, SubTaskEntity
from contenthive.models.task_parameters import (
    AuthorProfileDownloadSubParameters,
    MainTaskParameters,
    MediaDownloadSubParameters,
    ParseContentMainParameters,
    ParseContentSubParameters,
    SubTaskParameters,
    parse_main_task_parameters,
    parse_sub_task_parameters,
)
from contenthive.models.task_result import (
    AuthorProfileDownloadSubResult,
    ContentAnalysisSubResult,
    MainTaskResult,
    MediaDownloadSubResult,
    ParseContentMainResult,
    ParseContentSubResult,
    SubTaskResult,
    parse_main_task_result,
)
from contenthive.plugins.contracts import ParserMediaInfo, ParserResult
from contenthive.services.content import content_service
from contenthive.services.media import media_service
from contenthive.services.metadata import metadata_service
from contenthive.services.task_queue import task_queue
from contenthive.utils.content import resolve_content_id


def _encode_cursor(id: int, value: datetime | int) -> str:
    data = {"id": id, "value": value.isoformat() if isinstance(value, datetime) else value}
    payload = json.dumps(data, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    padding = 4 - len(cursor) % 4
    if padding != 4:
        cursor += "=" * padding
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor).decode())
        return int(data["id"]), str(data["value"])
    except (KeyError, ValueError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError) as e:
        raise ValueError("Invalid cursor") from e


class TaskService:
    """
    Service for managing task lifecycle and execution.
    """

    def __init__(self):
        """Initialize the TaskService."""
        # In-memory download progress for RUNNING sub tasks (SubTask.id → 0..100).
        # Not persisted; cleared on terminal status or process restart.
        self._live_progress: dict[int, int] = {}

    def set_live_progress(self, sub_task_id: int, progress: int) -> None:
        """Update in-memory progress for a RUNNING sub task (monotonic, 0-100)."""
        pct = max(0, min(100, int(progress)))
        previous = self._live_progress.get(sub_task_id, -1)
        if pct <= previous:
            return
        self._live_progress[sub_task_id] = pct

    def clear_live_progress(self, sub_task_id: int) -> None:
        """Remove in-memory progress for a sub task."""
        self._live_progress.pop(sub_task_id, None)

    def resolve_sub_task_progress(self, entity: SubTaskEntity) -> int | None:
        """Return in-memory live progress when present; otherwise None."""
        return self._live_progress.get(entity.id)

    def to_main_task_info(self, entity: MainTaskEntity, include_sub_tasks: bool = False) -> MainTaskInfo:
        """Build MainTaskInfo, overlaying live download progress onto sub tasks."""
        info = MainTaskInfo.from_entity(entity, include_sub_tasks=include_sub_tasks)
        if include_sub_tasks and entity.sub_tasks:
            for st_info, st_entity in zip(info.sub_tasks, entity.sub_tasks, strict=True):
                live = self.resolve_sub_task_progress(st_entity)
                if live is not None:
                    st_info.progress = live
        return info

    def _generate_task_id(self) -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:16]}"

    def _generate_sub_task_id(self) -> str:
        """Generate a unique sub task ID."""
        return f"subtask_{uuid.uuid4().hex[:16]}"

    # Main Task Methods

    async def create_parser_task(self, user_id: int, url: str, plugin_id: str | None = None) -> MainTaskInfo | None:
        """
        Create a new parser main task with deduplication logic.
        Task will be automatically enqueued for execution.

        Deduplication strategy:
        1. Check if there's a running PRIMARY task for this URL
           - If running PRIMARY exists and created by CURRENT user: Return existing task
           - If running PRIMARY exists and created by DIFFERENT user: Create LINKED task
           - If no running PRIMARY: Create PRIMARY task (new execution)

        Note:
            All actual work is done in SubTasks:
            - SubTask 1: Parse URL to get metadata and media list
            - SubTask 2-N: Download each media file

        Args:
            user_id: User ID who creates the task
            url: URL to be parsed
            plugin_id: Optional plugin ID to use for parsing

        Returns:
            Created MainTaskInfo object or None
        """
        parameters = ParseContentMainParameters(url=url, plugin_id=plugin_id)

        # Check if there's a running PRIMARY task for this URL
        with TaskDAO() as task_dao:
            running_primary = task_dao.find_running_primary_task_by_url(url)

        if running_primary:
            # Check if the running PRIMARY task was created by the current user
            if running_primary.user_id == user_id:
                # Same user - return existing task directly
                logger.debug(f"Returning existing PRIMARY task {running_primary.id} to user {user_id} (URL: {url})")
                return self.to_main_task_info(running_primary)
            else:
                # Different user - create LINKED task
                logger.debug(
                    f"Creating LINKED task for user {user_id}, linked to PRIMARY task {running_primary.id} (URL: {url})"
                )
                task_entity = await self.create_main_task(
                    user_id=user_id,
                    task_type=TaskType.PARSE_CONTENT,
                    url=url,
                    parameters=parameters,
                    role=TaskRole.LINKED,
                    primary_task_id=running_primary.id,
                )
                # LINKED tasks don't need to be executed, they wait for PRIMARY
                # No need to enqueue
        else:
            # No running PRIMARY task - create new PRIMARY task
            logger.debug(f"No running PRIMARY task for URL: {url}, creating new PRIMARY task")
            task_entity = await self.create_main_task(
                user_id=user_id,
                task_type=TaskType.PARSE_CONTENT,
                url=url,
                parameters=parameters,
                role=TaskRole.PRIMARY,
            )

            # Enqueue the task for execution
            if task_entity:
                task_queue.enqueue(task_entity.id, priority=0)

        if task_entity:
            return self.to_main_task_info(task_entity)
        return None

    async def create_main_task(
        self,
        user_id: int,
        task_type: TaskType,
        url: str,
        parameters: MainTaskParameters,
        role: TaskRole | None = None,
        primary_task_id: int | None = None,
        parse_result_id: int | None = None,
    ) -> MainTaskEntity | None:
        """
        Create a new main task.

        Args:
            user_id: User ID who creates the task
            task_type: Type of the task
            url: Target URL for the task
            parameters: Typed task parameters
            role: Task role (primary, linked)
            primary_task_id: ID of primary task if this is linked
            parse_result_id: Associated parse result ID

        Returns:
            Created MainTaskEntity object or None
        """
        try:
            task_id = self._generate_task_id()
            payload = parameters.model_dump(mode="json")

            with TaskDAO() as dao:
                id = dao.create_main_task(
                    task_id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                    url=url,
                    parameters=payload,
                    status=TaskStatus.PENDING,
                    role=role,
                    primary_task_id=primary_task_id,
                    parse_result_id=parse_result_id,
                    commit=True,
                )

                task = dao.get_main_task_by_id(id, include_sub_tasks=True)
                logger.debug(f"Created main task {task_id} (ID: {id}) for user {user_id}")
                return task
        except Exception:
            logger.exception("Failed to create main task")
            raise

    def get_main_task(self, id: int, include_sub_tasks: bool = False) -> MainTaskEntity | None:
        """
        Get main task by database ID.

        Args:
            id: Database ID of the task
            include_sub_tasks: Whether to load sub tasks

        Returns:
            MainTaskEntity object or None
        """
        with TaskDAO() as dao:
            task = dao.get_main_task_by_id(id, include_sub_tasks=include_sub_tasks)
            return task

    def get_main_task_by_task_id(self, task_id: str, include_sub_tasks: bool = False) -> MainTaskEntity | None:
        """
        Get main task by task ID string.

        Args:
            task_id: Unique task identifier
            include_sub_tasks: Whether to load sub tasks

        Returns:
            MainTaskEntity object or None
        """
        with TaskDAO() as dao:
            task = dao.get_main_task_by_task_id(task_id, include_sub_tasks=include_sub_tasks)
            return task

    def update_main_task_status(self, id: int, status: TaskStatus, error_message: str | None = None) -> bool:
        """
        Update main task status.

        Args:
            id: Database ID of the task
            status: New status
            error_message: Error message if failed

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_main_task_status(id, status, error_message, commit=True)

    def update_main_task_result(self, id: int, result: MainTaskResult) -> bool:
        """
        Update main task result.

        Args:
            id: Database ID of the task
            result: Typed task result

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_main_task_result(id, result.model_dump(mode="json"), commit=True)

    def update_main_task_parse_result_id(self, id: int, parse_result_id: int) -> bool:
        """
        Update main task's associated parse result ID.

        Args:
            id: Database ID of the task
            parse_result_id: Parse result ID to associate

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_main_task_parse_result_id(id, parse_result_id, commit=True)

    def list_main_tasks(
        self,
        user_id: int | None = None,
        task_type: TaskType | None = None,
        status: list[TaskStatus] | None = None,
        task_ids: list[str] | None = None,
        role: TaskRole | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MainTaskInfo]:
        """
        List main tasks with filters.

        Args:
            user_id: Filter by user ID
            task_type: Filter by task type
            status: Filter by status. Ignored when task_ids is provided.
            task_ids: Optional list of task IDs to filter by. When provided, status filter is ignored.
            role: Filter by role
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of MainTaskInfo objects
        """
        with TaskDAO() as dao:
            tasks, _ = dao.list_main_tasks(
                user_id=user_id,
                task_type=task_type,
                status=status,
                task_ids=task_ids,
                role=role,
                limit=limit,
                offset=offset,
            )
            return [self.to_main_task_info(task) for task in tasks]

    def list_main_tasks_by_user(
        self,
        user_id: int,
        status: list[TaskStatus] | None = None,
        task_ids: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        order: str = "desc",
        include_sub_tasks: bool = False,
    ) -> PaginatedResponse[MainTaskInfo]:
        """
        List main tasks for a specific user with pagination.

        Args:
            user_id: User ID to filter tasks
            status: Optional task status filter (e.g., pending, running, completed). Ignored when task_ids is provided.
            task_ids: Optional list of task IDs to filter by. When provided, status filter is ignored.
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by (id, created_at, updated_at)
            order: Sort direction (asc, desc)
            include_sub_tasks: Whether to eagerly load sub tasks

        Returns:
            PaginatedResponse containing list of MainTaskInfo and pagination info
        """
        try:
            offset = (page - 1) * page_size

            with TaskDAO() as dao:
                tasks, total = dao.list_main_tasks(
                    user_id=user_id,
                    status=status,
                    task_ids=task_ids,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order,
                    include_sub_tasks=include_sub_tasks,
                )

            items = [self.to_main_task_info(task, include_sub_tasks=include_sub_tasks) for task in tasks]
            total_pages = (total + page_size - 1) // page_size  # Ceiling division

            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(page=page, page_size=page_size, total=total, total_pages=total_pages),
            )
        except Exception:
            logger.exception(f"Error listing main tasks for user {user_id}")
            raise

    def list_main_tasks_by_user_with_cursor(
        self,
        user_id: int,
        status: list[TaskStatus] | None = None,
        task_ids: list[str] | None = None,
        cursor: str | None = None,
        limit: int = 20,
        sort_by: str = "created_at",
        order: str = "desc",
        include_sub_tasks: bool = False,
    ) -> CursorPaginatedResponse[MainTaskInfo]:
        """
        List main tasks for a specific user using cursor (keyset) pagination.

        Args:
            user_id: User ID to filter tasks
            status: Optional task status filter. Ignored when task_ids is provided.
            task_ids: Optional list of task IDs to filter by. When provided, status filter is ignored.
            cursor: Opaque cursor from the previous response; omit for the first page
            limit: Number of items per page (1-100)
            sort_by: Field to sort by (id, created_at, updated_at)
            order: Sort direction (asc, desc)
            include_sub_tasks: Whether to eagerly load sub tasks

        Returns:
            CursorPaginatedResponse containing items and next_cursor
        """
        cursor_id: int | None = None
        cursor_value: datetime | str | int | None = None

        if cursor is not None:
            cursor_id, cursor_value_raw = _decode_cursor(cursor)
            cursor_value = (
                datetime.fromisoformat(cursor_value_raw)
                if sort_by in {"created_at", "updated_at"}
                else int(cursor_value_raw)
            )

        with TaskDAO() as dao:
            tasks = dao.list_main_tasks_with_cursor(
                user_id=user_id,
                status=status,
                task_ids=task_ids,
                cursor_id=cursor_id,
                cursor_value=cursor_value,
                limit=limit + 1,
                sort_by=sort_by,
                order=order,
                include_sub_tasks=include_sub_tasks,
            )

        has_more = len(tasks) > limit
        tasks = tasks[:limit]

        next_cursor: str | None = None
        if has_more and tasks:
            last = tasks[-1]
            sort_value_map = {
                "id": last.id,
                "created_at": last.created_at,
                "updated_at": last.updated_at,
            }
            next_cursor = _encode_cursor(last.id, sort_value_map.get(sort_by, last.created_at))

        return CursorPaginatedResponse(
            items=[self.to_main_task_info(task, include_sub_tasks=include_sub_tasks) for task in tasks],
            next_cursor=next_cursor,
        )

    # Sub Task Methods

    def create_sub_task(
        self,
        main_task_id: int,
        task_type: TaskType,
        parameters: SubTaskParameters,
        depends_on_id: int | None = None,
    ) -> SubTaskEntity | None:
        """
        Create a new sub task.

        Args:
            main_task_id: Parent main task ID
            task_type: Type of the sub task
            parameters: Typed task parameters
            depends_on_id: ID of sub task this depends on

        Returns:
            Created SubTaskEntity object or None
        """
        try:
            sub_task_id = self._generate_sub_task_id()
            payload = parameters.model_dump(mode="json")

            with TaskDAO() as dao:
                sub_task_db_id = dao.create_sub_task(
                    sub_task_id=sub_task_id,
                    main_task_id=main_task_id,
                    task_type=task_type,
                    parameters=payload,
                    status=TaskStatus.PENDING,
                    depends_on_id=depends_on_id,
                    commit=True,
                )

                sub_task = dao.get_sub_task_by_id(sub_task_db_id)
                logger.debug(f"Created sub task {sub_task_id} (ID: {sub_task_db_id}) for main task {main_task_id}")
                return sub_task
        except Exception:
            logger.exception("Failed to create sub task")
            raise

    def get_sub_task(self, id: int) -> SubTaskEntity | None:
        """
        Get sub task by database ID.

        Args:
            id: Database ID of the sub task

        Returns:
            SubTaskEntity object or None
        """
        with TaskDAO() as dao:
            sub_task = dao.get_sub_task_by_id(id)
            return sub_task

    def get_sub_tasks_by_main_task(self, main_task_id: int) -> list[SubTaskEntity]:
        """
        Get all sub tasks for a main task.

        Args:
            main_task_id: Database ID of the main task

        Returns:
            List of SubTaskEntity objects
        """
        with TaskDAO() as dao:
            sub_tasks = dao.get_sub_tasks_by_main_task_id(main_task_id)
            return sub_tasks

    def update_sub_task_status(self, id: int, status: TaskStatus, error_message: str | None = None) -> bool:
        """
        Update sub task status.

        Args:
            id: Database ID of the sub task
            status: New status
            error_message: Error message if failed

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            updated = dao.update_sub_task_status(id, status, error_message, commit=True)
        if updated and status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
            self.clear_live_progress(id)
        return updated

    def update_sub_task_result(self, id: int, result: SubTaskResult) -> bool:
        """
        Update sub task result.

        Args:
            id: Database ID of the sub task
            result: Typed task result

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_sub_task_result(id, result.model_dump(mode="json"), commit=True)

    # Task Execution Methods

    async def execute_main_task(self, id: int) -> ParseContentMainResult | dict[str, Any]:
        """
        Execute a main task based on its type.

        Args:
            id: Database ID of the task

        Returns:
            Task execution result

        Note:
            This is the main entry point for task execution.
            Implementation delegates to specific task type handlers.
        """
        task = self.get_main_task(id)
        if not task:
            raise ValueError(f"Main task {id} not found")

        if task.status == TaskStatus.CANCELED:
            logger.info(f"Task {id} is already canceled, skipping execution")
            return {}

        if task.status != TaskStatus.PENDING:
            raise ValueError(f"Task {id} is not in PENDING state (current: {task.status})")

        logger.info(f"Executing main task {task.task_id} (ID: {id}, type: {task.type})")

        try:
            # Update status to RUNNING
            self.update_main_task_status(id, TaskStatus.RUNNING)

            # Route to specific task handler
            if task.type == TaskType.PARSE_CONTENT:
                result, parse_result_id = await self._execute_parse_content_task(task)
            else:
                raise ValueError(f"Unknown task type: {task.type}")

            # Update task result and status
            self.update_main_task_result(id, result)
            self.update_main_task_status(id, TaskStatus.COMPLETED)
            if parse_result_id:
                self.update_main_task_parse_result_id(id, parse_result_id)

            logger.info(f"Main task {task.task_id} (ID: {id}) completed successfully")
            return result

        except Exception as e:
            error_msg = f"Task execution failed: {e!s}"
            logger.exception(f"Main task {task.task_id} (ID: {id}) failed")
            self.update_main_task_status(id, TaskStatus.FAILED, error_message=error_msg)
            raise

    async def _execute_parse_content_task(self, task: MainTaskEntity) -> tuple[ParseContentMainResult, int | None]:
        """
        Execute a parse content task.

        Architecture: All work is done in SubTasks
        - MainTask: Orchestration and coordination only
        - SubTask 1: Parse URL to get metadata and media list (PARSE_CONTENT)
        - SubTask 2-N: Download each media file (MEDIA_DOWNLOAD)

        Execution flow:
        1. Create and execute parse sub task → get ParserResult
        2. Save parse result to database → get parse_result_id
        3. Create download sub tasks for each media (skip decided at execution)
        4. Execute all download sub tasks in parallel (each persists its own media row)
        5. Sync content sidecar and return task statistics

        Args:
            task: MainTaskEntity object

        Returns:
            Tuple of (task result summary, parse_result_id for the column)
        """
        logger.info(f"[{task.task_id}] Starting parse content task")

        parse_result = None
        parse_result_id = None
        parse_subtask = None
        download_subtasks = []

        try:
            # ========== Phase 1: Parameter Validation ==========
            main_params = parse_main_task_parameters(task.type, task.parameters)
            if main_params is None or not main_params.url:
                raise ValueError("URL parameter is required")
            url = main_params.url
            plugin_id = main_params.plugin_id

            # ========== Phase 2: Parse Content ==========
            parse_subtask = self.create_sub_task(
                main_task_id=task.id,
                task_type=TaskType.PARSE_CONTENT,
                parameters=ParseContentSubParameters(url=url, plugin_id=plugin_id),
            )

            if not parse_subtask:
                raise ValueError("Failed to create parse sub task")

            parse_result = await self._execute_parse_content_sub_task(parse_subtask)

            if not parse_result:
                raise ValueError("Parse sub task returned None")

            media_count = len(parse_result.media) if parse_result.media else 0
            platform_code = parse_result.platform.code if parse_result.platform else "unknown"
            author_uid = parse_result.author.uid if parse_result.author else "unknown"

            logger.info(
                f"[{task.task_id}] Parse completed: platform={platform_code},"
                f" author={author_uid}, media_count={media_count}"
            )

            # ========== Phase 3: Save Parse Result ==========
            # Capture the author's existing profile assets before save_parse_result
            # overwrites the avatar/banner URLs, so we can detect URL changes.
            author_profile_state = None
            if parse_result.author:
                try:
                    with ContentDAO() as content_dao:
                        author_profile_state = content_dao.get_author_profile_state(platform_code, author_uid)
                except Exception:
                    logger.exception(f"[{task.task_id}] Failed to read author profile state")

            try:
                with ContentDAO() as content_dao:
                    parse_result_id, orphan_media_paths = content_dao.save_parse_result(
                        parse_result, user_id=task.user_id
                    )
            except Exception as e:
                logger.exception(f"[{task.task_id}] Failed to save parse result")
                raise ValueError(f"Failed to save parse result to database: {e}") from e

            for relative_path in orphan_media_paths:
                media_service.delete_media_file(relative_path)

            metadata_service.sync_content_sidecar(parse_result_id, task.user_id)
            if parse_result.author:
                metadata_service.sync_author_sidecar(platform_code, author_uid)

            # ========== Phase 3.5: Download Author Avatar / Banner (one subtask each) ==========
            if parse_result.author:
                profile_subtasks: list[SubTaskEntity] = []
                avatar_url = str(parse_result.author.avatar) if parse_result.author.avatar else None
                banner_url = str(parse_result.author.banner) if parse_result.author.banner else None
                for asset, url, prev_url, prev_path in (
                    (
                        AuthorProfileAsset.AVATAR,
                        avatar_url,
                        author_profile_state.avatar if author_profile_state else None,
                        author_profile_state.avatar_path if author_profile_state else None,
                    ),
                    (
                        AuthorProfileAsset.BANNER,
                        banner_url,
                        author_profile_state.banner if author_profile_state else None,
                        author_profile_state.banner_path if author_profile_state else None,
                    ),
                ):
                    if not url:
                        continue
                    subtask = self.create_sub_task(
                        main_task_id=task.id,
                        task_type=TaskType.AUTHOR_PROFILE_DOWNLOAD,
                        parameters=AuthorProfileDownloadSubParameters(
                            asset=asset,
                            platform=platform_code,
                            author_uid=author_uid,
                            url=url,
                            prev_url=prev_url,
                            prev_path=prev_path,
                        ),
                        depends_on_id=parse_subtask.id,
                    )
                    if subtask:
                        profile_subtasks.append(subtask)

                if profile_subtasks:
                    # Best-effort: profile download failures must not fail the parse task.
                    results = await asyncio.gather(
                        *[self._execute_author_profile_download_sub_task(st) for st in profile_subtasks],
                        return_exceptions=True,
                    )
                    for subtask, outcome in zip(profile_subtasks, results, strict=True):
                        if isinstance(outcome, BaseException):
                            logger.error(
                                f"[{task.task_id}] Author profile download subtask {subtask.sub_task_id} failed",
                                exc_info=(type(outcome), outcome, outcome.__traceback__),
                            )
                    metadata_service.sync_author_sidecar(platform_code, author_uid)

            # ========== Phase 4: Handle Media Downloads ==========
            if not parse_result.media or media_count == 0:
                logger.warning(f"[{task.task_id}] No media found in parse result, skipping download phase")
                return self._build_task_result(
                    parse_result_id=parse_result_id,
                    media_count=0,
                    success_count=0,
                    saved_count=0,
                    failed_count=0,
                )

            # Create a download sub task for every media item; skip is decided at execution.
            content_id = resolve_content_id(parse_result.pid, str(parse_result.url))

            for idx, media in enumerate(parse_result.media):
                download_subtask = self.create_sub_task(
                    main_task_id=task.id,
                    task_type=TaskType.MEDIA_DOWNLOAD,
                    parameters=MediaDownloadSubParameters(
                        platform=platform_code,
                        author=author_uid,
                        content_id=content_id,
                        parse_result_id=parse_result_id,
                        plugin_domain=parse_result.parser,
                        media_index=idx,
                        media=media,
                    ),
                    depends_on_id=parse_subtask.id,
                )

                if download_subtask:
                    download_subtasks.append(download_subtask)
                else:
                    logger.warning(f"[{task.task_id}] Failed to create download sub task for media {idx}")

            if not download_subtasks:
                logger.warning(f"[{task.task_id}] No download sub tasks created")
                return self._build_task_result(
                    parse_result_id=parse_result_id,
                    media_count=media_count,
                    success_count=0,
                    saved_count=0,
                    failed_count=0,
                )

            logger.info(f"[{task.task_id}] Executing {len(download_subtasks)}/{media_count} downloads")

            MAX_CONCURRENT_DOWNLOADS = 5
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

            async def download_with_semaphore(subtask):
                async with semaphore:
                    return await self._execute_media_download_sub_task(subtask)

            download_results = await asyncio.gather(
                *[download_with_semaphore(subtask) for subtask in download_subtasks],
                return_exceptions=False,  # Let exceptions bubble up for proper handling
            )

            # ========== Phase 5: Process Download Results ==========
            success_count, saved_count, failed_count = self._categorize_download_results(
                task_id=task.task_id,
                download_results=download_results,
                download_subtasks=download_subtasks,
            )

            logger.info(
                f"[{task.task_id}] Download phase completed: "
                f"{success_count} new, {saved_count} on disk, {failed_count} failed"
            )

            # ========== Phase 6: Sync sidecar (media rows already saved in executors) ==========
            metadata_service.sync_content_sidecar(parse_result_id, task.user_id)

            # ========== Phase 7: Build and Return Result ==========
            result = self._build_task_result(
                parse_result_id=parse_result_id,
                media_count=media_count,
                success_count=success_count,
                saved_count=saved_count,
                failed_count=failed_count,
            )

            logger.info(
                f"[{task.task_id}] Parse content task completed: parse_result_id={parse_result_id}, "
                f"media={media_count}, success_count={success_count}, "
                f"saved={saved_count}, failed={failed_count}"
            )

            return result

        except Exception:
            logger.exception(f"[{task.task_id}] Parse content task failed")
            logger.debug(
                f"[{task.task_id}] Failure context: parse_result_id={parse_result_id}, "
                f"parse_subtask={'created' if parse_subtask else 'not created'}, "
                f"download_subtasks={len(download_subtasks)}"
            )
            raise

    async def _execute_author_profile_download_sub_task(
        self, sub_task: SubTaskEntity
    ) -> AuthorProfileDownloadSubResult:
        """
        Execute an author profile asset download sub task (avatar or banner).

        Re-downloads only when the remote URL changed or the local file is missing,
        then persists the resulting /media path and updates the sub task status.

        Args:
            sub_task: SubTaskEntity object

        Returns:
            Typed outcome for this single asset.
        """
        params = parse_sub_task_parameters(sub_task.type, sub_task.parameters)

        try:
            if not isinstance(params, AuthorProfileDownloadSubParameters):
                raise ValueError("platform, author_uid, and asset parameters are required")

            asset = params.asset
            self.update_sub_task_status(sub_task.id, TaskStatus.RUNNING)

            url_changed = params.prev_url != params.url
            file_missing = not media_service.media_file_exists(params.prev_path)
            if not url_changed and not file_missing:
                logger.debug(f"[{sub_task.sub_task_id}] Author {asset} unchanged, skipping download")
                result = AuthorProfileDownloadSubResult(
                    status=SubTaskResultStatus.SKIPPED,
                    asset=asset,
                    path=params.prev_path,
                )
                self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
                self.update_sub_task_result(sub_task.id, result)
                return result

            path = await media_service.download_author_profile_asset(
                platform=params.platform,
                author_uid=params.author_uid,
                asset=asset,
                url=params.url,
                on_progress=lambda pct, sid=sub_task.id: self.set_live_progress(sid, pct),
            )

            if path is None:
                error_message = f"Author {asset} download failed"
                result = AuthorProfileDownloadSubResult(
                    status=SubTaskResultStatus.FAILED,
                    asset=asset,
                )
                self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_message)
                self.update_sub_task_result(sub_task.id, result)
                return result

            with ContentDAO() as content_dao:
                current_state = content_dao.get_author_profile_state(params.platform, params.author_uid)
                author_id = current_state.id if current_state else None
                if author_id is None:
                    logger.warning(f"[{sub_task.sub_task_id}] Author not found after save, cannot persist {asset} path")
                elif asset == AuthorProfileAsset.AVATAR:
                    content_dao.update_author_profile_paths(author_id=author_id, avatar_path=path)
                else:
                    content_dao.update_author_profile_paths(author_id=author_id, banner_path=path)

            result = AuthorProfileDownloadSubResult(
                status=SubTaskResultStatus.SUCCESS,
                asset=asset,
                path=path,
            )
            self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
            self.update_sub_task_result(sub_task.id, result)
            logger.info(f"[{sub_task.sub_task_id}] Author {asset} download success: {path}")
            return result

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Author profile download sub task {sub_task.sub_task_id} failed")
            asset = params.asset if isinstance(params, AuthorProfileDownloadSubParameters) else None
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            self.update_sub_task_result(
                sub_task.id,
                AuthorProfileDownloadSubResult(status=SubTaskResultStatus.FAILED, asset=asset),
            )
            raise

    @staticmethod
    def _should_skip_media_download(existing: MediaEntity, media: ParserMediaInfo) -> bool:
        """
        Whether a MEDIA_DOWNLOAD sub task can skip the actual download.

        Evaluated at sub task execution time. Requires COMPLETED status and a
        present main media file. If the parse result still advertises a cover
        (or cover fallbacks), the local cover file must also exist — otherwise a
        missing cover would never be retried.
        """
        if existing.status != MediaStatus.COMPLETED:
            return False
        if not media_service.media_file_exists(existing.media_path):
            return False
        expects_cover = bool(media.cover) or bool(media.cover_fallbacks)
        return (not expects_cover) or media_service.media_file_exists(existing.cover_path)

    def _categorize_download_results(
        self,
        task_id: str,
        download_results: list[MediaDownloadSubResult],
        download_subtasks: list[SubTaskEntity],
    ) -> tuple[int, int, int]:
        """
        Categorize download sub task results.

        Args:
            task_id: Main task ID for logging
            download_results: List of media download sub task results
            download_subtasks: List of download sub tasks

        Returns:
            Tuple of (success_count, saved_count, failed_count) where
            success_count is this-run SUCCESS count and saved_count is
            SUCCESS + SKIPPED (present on disk after this run).
        """
        success_count = 0
        saved_count = 0
        failed_count = 0

        for idx, result in enumerate(download_results):
            subtask_id = download_subtasks[idx].sub_task_id if idx < len(download_subtasks) else None

            if result.status == SubTaskResultStatus.SUCCESS:
                success_count += 1
                saved_count += 1
            elif result.status == SubTaskResultStatus.SKIPPED:
                saved_count += 1
                logger.debug(f"[{task_id}] Download [{idx + 1}/{len(download_results)}] skipped: {subtask_id}")
            elif result.status == SubTaskResultStatus.FAILED:
                failed_count += 1
                logger.warning(f"[{task_id}] Download [{idx + 1}/{len(download_results)}] failed: {subtask_id}")
            else:
                failed_count += 1
                logger.warning(
                    f"[{task_id}] Download [{idx + 1}/{len(download_results)}] unexpected status: "
                    f"{subtask_id} - {result.status}"
                )

        return success_count, saved_count, failed_count

    def _build_task_result(
        self,
        parse_result_id: int | None,
        media_count: int,
        success_count: int,
        saved_count: int,
        failed_count: int,
    ) -> tuple[ParseContentMainResult, int | None]:
        """
        Build comprehensive task result model.

        Args:
            parse_result_id: Saved parse result ID (returned separately for the column)
            media_count: Total media count from parse result
            success_count: Newly downloaded in this run (sub task SUCCESS)
            saved_count: On disk after this run (SUCCESS + SKIPPED)
            failed_count: Number of failed downloads

        Returns:
            Tuple of (task result summary, parse_result_id)
        """
        return (
            ParseContentMainResult(
                media_count=media_count,
                success_count=success_count,
                saved_count=saved_count,
                failed_count=failed_count,
            ),
            parse_result_id,
        )

    async def _execute_parse_content_sub_task(self, sub_task: SubTaskEntity) -> ParserResult:
        """
        Execute a parse content sub task.
        This sub task parses the URL to extract content metadata and media list.

        Args:
            sub_task: SubTaskEntity object

        Returns:
            ParserResult object containing parsed content metadata and media list
        """
        try:
            params = parse_sub_task_parameters(sub_task.type, sub_task.parameters)
            if not isinstance(params, ParseContentSubParameters) or not params.url:
                raise ValueError("URL parameter is required")

            # Get main task to get user_id
            main_task = self.get_main_task(sub_task.main_task_id)
            if not main_task:
                raise ValueError(f"Main task {sub_task.main_task_id} not found")

            # Update sub task status to RUNNING
            self.update_sub_task_status(sub_task.id, TaskStatus.RUNNING)

            # Parse content
            parse_result = await content_service.parser_content(url=params.url, plugin_id=params.plugin_id)

            if not parse_result:
                raise ValueError(f"Failed to parse content from URL: {params.url}")

            # Update sub task status to COMPLETED
            self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)

            # Save sub task result
            self.update_sub_task_result(
                sub_task.id,
                ParseContentSubResult(
                    status=SubTaskResultStatus.SUCCESS,
                    platform=parse_result.platform.code if parse_result.platform else None,
                    author=parse_result.author.username if parse_result.author else None,
                    content_id=resolve_content_id(
                        parse_result.pid,
                        str(parse_result.url),
                    ),
                    media_count=len(parse_result.media) if parse_result.media else 0,
                    url=str(parse_result.url) if parse_result.url else None,
                ),
            )
            return parse_result

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Parse sub task {sub_task.sub_task_id} failed")

            # Update sub task status to FAILED
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            self.update_sub_task_result(
                sub_task.id,
                ParseContentSubResult(status=SubTaskResultStatus.FAILED),
            )

            # Re-raise exception to propagate to main task
            raise

    async def _execute_media_download_sub_task(self, sub_task: SubTaskEntity) -> MediaDownloadSubResult:
        """
        Execute a media download sub task.

        Skips when the media is already COMPLETED with local files present.
        Otherwise downloads, persists the media row, and updates the sub task.

        Args:
            sub_task: SubTaskEntity object

        Returns:
            MediaDownloadSubResult for this media item
        """
        params = parse_sub_task_parameters(sub_task.type, sub_task.parameters)
        if not isinstance(params, MediaDownloadSubParameters):
            error_msg = "Invalid MEDIA_DOWNLOAD parameters"
            logger.error(f"[{sub_task.sub_task_id}] {error_msg}: {sub_task.parameters!r}")
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            result = MediaDownloadSubResult(status=SubTaskResultStatus.FAILED)
            self.update_sub_task_result(sub_task.id, result)
            return result

        try:
            main_task = self.get_main_task(sub_task.main_task_id)
            if not main_task:
                raise ValueError(f"Main task {sub_task.main_task_id} not found")

            self.update_sub_task_status(sub_task.id, TaskStatus.RUNNING)

            media_url = str(params.media.url)
            existing: MediaEntity | None = None
            try:
                with ContentDAO() as content_dao:
                    existing = content_dao.get_media_by_parse_result_url(params.parse_result_id, media_url)
            except Exception:
                logger.exception(f"[{sub_task.sub_task_id}] Failed to load existing media for download skip check")

            if existing is not None and self._should_skip_media_download(existing, params.media):
                logger.debug(f"[{sub_task.sub_task_id}] Skipping download: already completed with local file")
                result = MediaDownloadSubResult(
                    status=SubTaskResultStatus.SKIPPED,
                    media_path=existing.media_path,
                )
                self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
                self.update_sub_task_result(sub_task.id, result)
                return result

            downloaded = await media_service.download_media(
                platform=params.platform,
                author=params.author,
                content_id=params.content_id,
                media=params.media,
                media_index=params.media_index,
                plugin_domain=params.plugin_domain,
                on_progress=lambda pct, sid=sub_task.id: self.set_live_progress(sid, pct),
            )

            if downloaded is None:
                logger.warning(f"Media download sub task {sub_task.sub_task_id} returned None")
                try:
                    with ContentDAO() as content_dao:
                        content_dao.save_downloaded_media(
                            DownloadedMediaInfo(
                                status=MediaStatus.FAILED,
                                url=params.media.url,
                                type=params.media.type,
                                title=params.media.title,
                                cover=params.media.cover,
                                url_fallbacks=params.media.url_fallbacks or [],
                                cover_fallbacks=params.media.cover_fallbacks or [],
                                duration=params.media.duration,
                                width=params.media.width,
                                height=params.media.height,
                                media_path=None,
                                cover_path=None,
                            ),
                            params.parse_result_id,
                            order=params.media_index,
                            commit=True,
                        )
                except Exception:
                    logger.exception(f"[{sub_task.sub_task_id}] Failed to persist FAILED media status")
                result = MediaDownloadSubResult(status=SubTaskResultStatus.FAILED)
                self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message="Download returned None")
                self.update_sub_task_result(sub_task.id, result)
                return result

            try:
                with ContentDAO() as content_dao:
                    content_dao.save_downloaded_media(
                        downloaded,
                        params.parse_result_id,
                        order=params.media_index,
                        commit=True,
                    )
            except Exception:
                logger.exception(f"[{sub_task.sub_task_id}] Failed to save downloaded media")
                result = MediaDownloadSubResult(status=SubTaskResultStatus.FAILED)
                self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message="Failed to save media record")
                self.update_sub_task_result(sub_task.id, result)
                return result

            result = MediaDownloadSubResult(
                status=SubTaskResultStatus.SUCCESS,
                media_path=downloaded.media_path,
            )
            self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
            self.update_sub_task_result(sub_task.id, result)
            return result

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Media download sub task {sub_task.sub_task_id} failed")
            try:
                with ContentDAO() as content_dao:
                    content_dao.save_downloaded_media(
                        DownloadedMediaInfo(
                            status=MediaStatus.FAILED,
                            url=params.media.url,
                            type=params.media.type,
                            title=params.media.title,
                            cover=params.media.cover,
                            url_fallbacks=params.media.url_fallbacks or [],
                            cover_fallbacks=params.media.cover_fallbacks or [],
                            duration=params.media.duration,
                            width=params.media.width,
                            height=params.media.height,
                            media_path=None,
                            cover_path=None,
                        ),
                        params.parse_result_id,
                        order=params.media_index,
                        commit=True,
                    )
            except Exception:
                logger.exception(f"[{sub_task.sub_task_id}] Failed to persist FAILED media status")
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            result = MediaDownloadSubResult(status=SubTaskResultStatus.FAILED)
            self.update_sub_task_result(sub_task.id, result)
            return result

    async def _execute_content_analysis_sub_task(self, sub_task: SubTaskEntity) -> ContentAnalysisSubResult:
        """
        Execute a content analysis sub task.

        Args:
            sub_task: SubTaskEntity object

        Returns:
            Task result

        Note:
            This method should be implemented with actual analysis logic.
        """
        logger.debug(f"Executing content analysis sub task {sub_task.sub_task_id}")

        # TODO: Implement actual analysis logic for sub task

        # Placeholder implementation
        return ContentAnalysisSubResult(
            status=SubTaskResultStatus.COMPLETED,
            sub_task_id=sub_task.sub_task_id,
            task_type=sub_task.type.value,
            parameters=sub_task.parameters,
            message="Content analysis sub task placeholder - implementation pending",
        )

    # Task Management Methods

    async def cancel_main_task(self, id: int) -> bool:
        """
        Cancel a main task and all its sub tasks.
        If the task is a PRIMARY task, linked tasks waiting for it will be promoted.

        Args:
            id: Database ID of the task

        Returns:
            True if cancelled successfully
        """
        try:
            task = self.get_main_task(id)
            if not task:
                raise ValueError(f"Main task {id} not found")

            if task.status in [
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELED,
            ]:
                logger.warning(f"Cannot cancel task {id} in state {task.status}")
                return False

            # Cancel all sub tasks
            sub_tasks = self.get_sub_tasks_by_main_task(id)
            for sub_task in sub_tasks:
                if sub_task.status not in [
                    TaskStatus.COMPLETED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELED,
                ]:
                    self.update_sub_task_status(sub_task.id, TaskStatus.CANCELED)

            # Cancel main task
            self.update_main_task_status(id, TaskStatus.CANCELED)
            logger.info(f"Cancelled main task {id} and {len(sub_tasks)} sub tasks")

            # Remove from queue or cancel the running asyncio task
            task_queue.remove(id)

            # Promote a linked task to PRIMARY if this was a PRIMARY task
            if task.role == TaskRole.PRIMARY:
                await self.promote_linked_tasks(id)

            return True

        except Exception:
            logger.exception(f"Failed to cancel main task {id}")
            raise

    def retry_main_task(self, id: int) -> bool:
        """
        Retry a failed main task.

        Args:
            id: Database ID of the task

        Returns:
            True if reset successfully

        Note:
            This resets the task to PENDING state. Call execute_main_task to run it.
        """
        try:
            task = self.get_main_task(id)
            if not task:
                raise ValueError(f"Main task {id} not found")

            if task.status != TaskStatus.FAILED:
                logger.warning(f"Cannot retry task {id} in state {task.status}")
                return False

            # Reset task to PENDING
            self.update_main_task_status(id, TaskStatus.PENDING, error_message=None)

            # Reset all failed sub tasks
            sub_tasks = self.get_sub_tasks_by_main_task(id)
            for sub_task in sub_tasks:
                if sub_task.status == TaskStatus.FAILED:
                    self.update_sub_task_status(sub_task.id, TaskStatus.PENDING, error_message=None)

            logger.info(f"Reset main task {id} for retry")
            return True

        except Exception:
            logger.exception(f"Failed to retry main task {id}")
            raise

    # Task Monitoring and Completion

    async def promote_linked_tasks(self, canceled_primary_id: int) -> None:
        """
        When a PRIMARY task is canceled, promote the earliest linked task to PRIMARY
        and re-point all other linked tasks to the new PRIMARY.

        Args:
            canceled_primary_id: Database ID of the canceled PRIMARY task
        """
        try:
            with TaskDAO() as dao:
                linked_tasks, _ = dao.list_main_tasks(
                    task_type=TaskType.PARSE_CONTENT,
                    role=TaskRole.LINKED,
                    status=[TaskStatus.PENDING],
                    primary_task_id=canceled_primary_id,
                    sort_by="created_at",
                    order="asc",
                    limit=10000,
                )

            if not linked_tasks:
                return

            new_primary = linked_tasks[0]
            remaining = linked_tasks[1:]

            with TaskDAO() as dao:
                dao.bulk_update_linked_task_primary(
                    task_ids=[t.id for t in remaining],
                    new_primary_id=new_primary.id,
                    new_primary_role=TaskRole.PRIMARY,
                )

            task_queue.enqueue(new_primary.id)
            logger.info(
                f"Promoted linked task {new_primary.id} to PRIMARY "
                f"(was waiting for canceled task {canceled_primary_id}), "
                f"{len(remaining)} other linked tasks re-pointed"
            )

        except Exception:
            logger.exception(f"Failed to promote linked tasks for canceled primary {canceled_primary_id}")

    async def monitor_and_complete_linked_tasks(self, primary_task_id: int) -> None:
        """
        Monitor a primary task and complete all linked tasks when it finishes.
        Should be called after a primary task completes.

        Args:
            primary_task_id: Database ID of the completed primary task
        """
        try:
            # Get the primary task
            primary_task = self.get_main_task(primary_task_id)
            if not primary_task:
                logger.warning(f"Primary task {primary_task_id} not found")
                return

            if primary_task.status != TaskStatus.COMPLETED:
                logger.warning(f"Primary task {primary_task_id} is not completed (status: {primary_task.status})")
                return

            # Find all linked tasks waiting for this primary task
            with TaskDAO() as dao:
                waiting_tasks, _ = dao.list_main_tasks(
                    task_type=TaskType.PARSE_CONTENT,
                    role=TaskRole.LINKED,
                    status=[TaskStatus.PENDING],
                    primary_task_id=primary_task_id,
                    limit=10000,
                )

            if not waiting_tasks:
                logger.debug(f"No linked tasks waiting for primary task {primary_task_id}")
                return

            logger.info(f"Completing {len(waiting_tasks)} linked tasks for primary task {primary_task_id}")

            # Complete all linked tasks with the same result
            for linked_task in waiting_tasks:
                try:
                    primary_result = parse_main_task_result(TaskType.PARSE_CONTENT, primary_task.result)
                    if primary_result is None:
                        primary_result = ParseContentMainResult()
                    linked_payload = primary_result.model_dump(mode="json")
                    with TaskDAO() as dao:
                        dao.update_main_task_status(linked_task.id, TaskStatus.COMPLETED, commit=False)
                        if primary_task.parse_result_id is not None:
                            dao.update_main_task_result(linked_task.id, linked_payload, commit=False)
                            dao.update_main_task_parse_result_id(
                                linked_task.id,
                                primary_task.parse_result_id,
                                commit=True,
                            )
                        else:
                            dao.update_main_task_result(linked_task.id, linked_payload, commit=True)
                    logger.debug(f"Completed linked task {linked_task.task_id} (ID: {linked_task.id})")
                except Exception:
                    logger.exception(f"Failed to complete linked task {linked_task.id}")

        except Exception:
            logger.exception(f"Failed to monitor linked tasks for primary {primary_task_id}")

    async def fail_linked_tasks(self, primary_task_id: int) -> None:
        """
        Mark all linked tasks as failed/canceled when the primary task fails or is canceled.
        Should be called after a primary task fails or is canceled.

        Args:
            primary_task_id: Database ID of the failed/canceled primary task
        """
        try:
            # Get the primary task
            primary_task = self.get_main_task(primary_task_id)
            if not primary_task:
                logger.warning(f"Primary task {primary_task_id} not found")
                return

            if primary_task.status not in (TaskStatus.FAILED, TaskStatus.CANCELED):
                logger.warning(
                    f"Primary task {primary_task_id} is not failed or canceled (status: {primary_task.status})"
                )
                return

            # Find all linked tasks waiting for this primary task
            with TaskDAO() as dao:
                waiting_tasks, _ = dao.list_main_tasks(
                    task_type=TaskType.PARSE_CONTENT,
                    role=TaskRole.LINKED,
                    status=[TaskStatus.PENDING],
                    primary_task_id=primary_task_id,
                    limit=10000,
                )

            if not waiting_tasks:
                logger.debug(f"No linked tasks waiting for primary task {primary_task_id}")
                return

            logger.info(
                f"Marking {len(waiting_tasks)} linked tasks as {primary_task.status.value}"
                f" for primary task {primary_task_id}"
            )

            # Mark all linked tasks with the same status and error
            for linked_task in waiting_tasks:
                try:
                    error_message = (
                        f"Primary task failed: {primary_task.error_message}"
                        if primary_task.error_message
                        else "Primary task failed"
                    )

                    with TaskDAO() as dao:
                        dao.update_main_task_status(
                            linked_task.id,
                            primary_task.status,  # Use the same status as primary (FAILED or CANCELED)
                            error_message=error_message,
                            commit=True,
                        )
                    logger.debug(
                        f"Marked linked task {linked_task.task_id} (ID: {linked_task.id})"
                        f" as {primary_task.status.value}"
                    )
                except Exception:
                    logger.exception(f"Failed to update linked task {linked_task.id}")

        except Exception:
            logger.exception(f"Failed to fail linked tasks for primary {primary_task_id}")


# Singleton instance
task_service = TaskService()
