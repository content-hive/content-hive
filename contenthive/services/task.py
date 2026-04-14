"""
Task service for managing and executing tasks.
"""

import hashlib
from typing import Optional, List, Dict, Any
import uuid
import asyncio

from contenthive.logger import logger
from contenthive.database.task_dao import TaskDAO
from contenthive.database.content_dao import ContentDAO
from contenthive.models.content import DownloadedMediaInfo, PaginatedResponse, PaginationInfo
from contenthive.models.enumerates import MediaStatus, TaskType, TaskStatus, TaskRole
from contenthive.plugins.contracts import ParserMediaInfo, ParserResult
from contenthive.models.task import MainTaskEntity, MainTaskInfo, SubTaskEntity
from contenthive.services.task_queue import task_queue
from contenthive.services.content import content_service
from contenthive.services.media import media_service

class TaskService:
    """
    Service for managing task lifecycle and execution.
    """
    
    def __init__(self):
        """Initialize the TaskService."""
        pass

    def _generate_task_id(self) -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:16]}"

    def _generate_sub_task_id(self) -> str:
        """Generate a unique sub task ID."""
        return f"subtask_{uuid.uuid4().hex[:16]}"

    # Main Task Methods

    async def create_parser_task(
        self,
        user_id: int,
        url: str,
        plugin_id: Optional[str] = None
    ) -> Optional[MainTaskInfo]:
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
        parameters = {
            "url": url,
            "plugin_id": plugin_id
        }
        
        # Check if there's a running PRIMARY task for this URL
        with TaskDAO() as task_dao:
            running_primary = task_dao.find_running_primary_task_by_url(url)
        
        if running_primary:
            # Check if the running PRIMARY task was created by the current user
            if running_primary.user_id == user_id:
                # Same user - return existing task directly
                logger.debug(f"Returning existing PRIMARY task {running_primary.id} to user {user_id} (URL: {url})")
                return MainTaskInfo.from_entity(running_primary)
            else:
                # Different user - create LINKED task
                logger.debug(f"Creating LINKED task for user {user_id}, linked to PRIMARY task {running_primary.id} (URL: {url})")
                task_entity = await self.create_main_task(
                    user_id=user_id,
                    task_type=TaskType.PARSE_CONTENT,
                    url=url,
                    parameters=parameters,
                    role=TaskRole.LINKED,
                    primary_task_id=running_primary.id
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
                role=TaskRole.PRIMARY
            )
            
            # Enqueue the task for execution
            if task_entity:
                task_queue.enqueue(task_entity.id, priority=0)
        
        if task_entity:
            return MainTaskInfo.from_entity(task_entity)
        return None

        
    async def create_main_task(
        self,
        user_id: int,
        task_type: TaskType,
        url: str,
        parameters: dict,
        role: Optional[TaskRole] = None,
        primary_task_id: Optional[int] = None,
        parse_result_id: Optional[int] = None
    ) -> Optional[MainTaskEntity]:
        """
        Create a new main task.

        Args:
            user_id: User ID who creates the task
            task_type: Type of the task
            url: Target URL for the task
            parameters: Task parameters
            role: Task role (primary, linked, reused)
            primary_task_id: ID of primary task if this is linked/reused
            parse_result_id: Associated parse result ID

        Returns:
            Created MainTaskEntity object or None
        """
        try:
            task_id = self._generate_task_id()
            
            with TaskDAO() as dao:
                id = dao.create_main_task(
                    task_id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                    url=url,
                    parameters=parameters,
                    status=TaskStatus.PENDING,
                    role=role,
                    primary_task_id=primary_task_id,
                    parse_result_id=parse_result_id,
                    commit=True
                )
                
                task = dao.get_main_task_by_id(id, include_sub_tasks=True)
                logger.debug(f"Created main task {task_id} (ID: {id}) for user {user_id}")
                return task
        except Exception as e:
            logger.exception(f"Failed to create main task")
            raise

    def get_main_task(self, id: int, include_sub_tasks: bool = False) -> Optional[MainTaskEntity]:
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

    def get_main_task_by_task_id(self, task_id: str, include_sub_tasks: bool = False) -> Optional[MainTaskEntity]:
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

    def update_main_task_status(
        self,
        id: int,
        status: TaskStatus,
        error_message: Optional[str] = None
    ) -> bool:
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

    def update_main_task_result(self, id: int, result: dict) -> bool:
        """
        Update main task result.

        Args:
            id: Database ID of the task
            result: Task result

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_main_task_result(id, result, commit=True)

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
        user_id: Optional[int] = None,
        task_type: Optional[TaskType] = None,
        status: Optional[TaskStatus] = None,
        role: Optional[TaskRole] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[MainTaskInfo]:
        """
        List main tasks with filters.

        Args:
            user_id: Filter by user ID
            task_type: Filter by task type
            status: Filter by status
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
                role=role,
                limit=limit,
                offset=offset
            )
            return [MainTaskInfo.from_entity(task) for task in tasks]

    def list_main_tasks_by_user(
            self,
            user_id: int,
            status: Optional[TaskStatus] = None,
            page: int = 1,
            page_size: int = 20,
            sort_by: str = "created_at",
            order: str = "desc"
    ) -> PaginatedResponse[MainTaskInfo]:
        """
        List main tasks for a specific user with pagination.

        Args:
            user_id: User ID to filter tasks
            status: Optional task status filter (e.g., pending, running, completed)
            page: Page number (starting from 1)
            page_size: Number of items per page
            sort_by: Field to sort by (id, created_at, updated_at)
            order: Sort direction (asc, desc)

        Returns:
            PaginatedResponse containing list of MainTaskInfo and pagination info
        """
        try:
            offset = (page - 1) * page_size
            
            with TaskDAO() as dao:
                tasks, total = dao.list_main_tasks(
                    user_id=user_id,
                    status=status,
                    limit=page_size,
                    offset=offset,
                    sort_by=sort_by,
                    order=order
                )
            
            items = [MainTaskInfo.from_entity(task) for task in tasks]
            total_pages = (total + page_size - 1) // page_size  # Ceiling division
            
            return PaginatedResponse(
                items=items,
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total=total,
                    total_pages=total_pages
                )
            )
        except Exception as e:
            logger.exception(f"Error listing main tasks for user {user_id}")
            raise

    # Sub Task Methods

    def create_sub_task(
        self,
        main_task_id: int,
        task_type: TaskType,
        parameters: dict,
        depends_on_id: Optional[int] = None
    ) -> Optional[SubTaskEntity]:
        """
        Create a new sub task.

        Args:
            main_task_id: Parent main task ID
            task_type: Type of the sub task
            parameters: Task parameters
            depends_on_id: ID of sub task this depends on

        Returns:
            Created SubTaskEntity object or None
        """
        try:
            sub_task_id = self._generate_sub_task_id()
            
            with TaskDAO() as dao:
                sub_task_db_id = dao.create_sub_task(
                    sub_task_id=sub_task_id,
                    main_task_id=main_task_id,
                    task_type=task_type,
                    parameters=parameters,
                    status=TaskStatus.PENDING,
                    depends_on_id=depends_on_id,
                    commit=True
                )
                
                sub_task = dao.get_sub_task_by_id(sub_task_db_id)
                logger.debug(f"Created sub task {sub_task_id} (ID: {sub_task_db_id}) for main task {main_task_id}")
                return sub_task
        except Exception as e:
            logger.exception(f"Failed to create sub task")
            raise

    def get_sub_task(self, id: int) -> Optional[SubTaskEntity]:
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

    def get_sub_tasks_by_main_task(self, main_task_id: int) -> List[SubTaskEntity]:
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

    def update_sub_task_status(
        self,
        id: int,
        status: TaskStatus,
        error_message: Optional[str] = None
    ) -> bool:
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
            return dao.update_sub_task_status(id, status, error_message, commit=True)

    def update_sub_task_progress(self, id: int, progress: int) -> bool:
        """
        Update sub task progress.

        Args:
            id: Database ID of the sub task
            progress: Progress percentage (0-100)

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_sub_task_progress(id, progress, commit=True)

    def update_sub_task_result(self, id: int, result: dict) -> bool:
        """
        Update sub task result.

        Args:
            id: Database ID of the sub task
            result: Task result

        Returns:
            True if updated successfully
        """
        with TaskDAO() as dao:
            return dao.update_sub_task_result(id, result, commit=True)

    # Task Execution Methods

    async def execute_main_task(self, id: int) -> Dict[str, Any]:
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

        if task.status != TaskStatus.PENDING:
            raise ValueError(f"Task {id} is not in PENDING state (current: {task.status})")

        logger.info(f"Executing main task {task.task_id} (ID: {id}, type: {task.type})")

        try:
            # Update status to RUNNING
            self.update_main_task_status(id, TaskStatus.RUNNING)

            # Route to specific task handler
            if task.type == TaskType.PARSE_CONTENT:
                result = await self._execute_parse_content_task(task)
            else:
                raise ValueError(f"Unknown task type: {task.type}")

            # Update task result and status
            self.update_main_task_result(id, result)
            self.update_main_task_status(id, TaskStatus.COMPLETED)
            result_id = result.get("parse_result_id")
            if result_id:
                self.update_main_task_parse_result_id(id, result_id)

            logger.info(f"Main task {task.task_id} (ID: {id}) completed successfully")
            return result

        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            logger.exception(f"Main task {task.task_id} (ID: {id}) failed")
            self.update_main_task_status(id, TaskStatus.FAILED, error_message=error_msg)
            raise

    async def _execute_parse_content_task(self, task: MainTaskEntity) -> Dict[str, Any]:
        """
        Execute a parse content task.
        
        Architecture: All work is done in SubTasks
        - MainTask: Orchestration and coordination only
        - SubTask 1: Parse URL to get metadata and media list (PARSE_CONTENT)
        - SubTask 2-N: Download each media file (MEDIA_DOWNLOAD)
        
        Execution flow:
        1. Create and execute parse sub task → get ParserResult
        2. Save parse result to database → get parse_result_id
        3. Create download sub tasks for each media (if any)
        4. Execute all download sub tasks in parallel
        5. Save all download results to database
        6. Return comprehensive task statistics

        Args:
            task: MainTaskEntity object

        Returns:
            Task result with parse_result_id, media statistics, and sub task details
        """
        logger.info(f"[{task.task_id}] Starting parse content task")
        
        parse_result = None
        parse_result_id = None
        parse_subtask = None
        download_subtasks = []
        
        try:
            # ========== Phase 1: Parameter Validation ==========
            url = task.parameters.get("url")
            plugin_id = task.parameters.get("plugin_id")
            
            if not url:
                raise ValueError("URL parameter is required")
            
            # ========== Phase 2: Parse Content ==========
            parse_subtask = self.create_sub_task(
                main_task_id=task.id,
                task_type=TaskType.PARSE_CONTENT,
                parameters={
                    "url": url,
                    "plugin_id": plugin_id
                }
            )
            
            if not parse_subtask:
                raise ValueError("Failed to create parse sub task")
            
            parse_result = await self._execute_parse_content_sub_task(parse_subtask)
            
            if not parse_result:
                raise ValueError("Parse sub task returned None")
            
            media_count = len(parse_result.media) if parse_result.media else 0
            platform_code = parse_result.platform.code if parse_result.platform else "unknown"
            author_uid = parse_result.author.uid if parse_result.author else "unknown"
            
            logger.info(f"[{task.task_id}] Parse completed: platform={platform_code}, author={author_uid}, media_count={media_count}")
            
            # ========== Phase 3: Save Parse Result ==========
            try:
                with ContentDAO() as content_dao:
                    parse_result_id = content_dao.save_parse_result(parse_result, user_id=task.user_id)
            except Exception as e:
                logger.exception(f"[{task.task_id}] Failed to save parse result")
                raise ValueError(f"Failed to save parse result to database: {e}")
            
            # ========== Phase 4: Handle Media Downloads ==========
            if not parse_result.media or media_count == 0:
                logger.warning(f"[{task.task_id}] No media found in parse result, skipping download phase")
                return self._build_task_result(
                    task_id=task.task_id,
                    parse_result_id=parse_result_id,
                    parse_subtask=parse_subtask,
                    media_count=0,
                    download_subtasks=[],
                    success_downloads=[],
                    failed_downloads=[],
                    saved_media_count=0,
                    saved_media_ids=[]
                )
            
            # Create download sub tasks
            content_id = parse_result.pid if parse_result.pid else hashlib.md5(str(parse_result.url).encode()).hexdigest()[:16]
            
            for idx, media in enumerate(parse_result.media):
                download_subtask = self.create_sub_task(
                    main_task_id=task.id,
                    task_type=TaskType.MEDIA_DOWNLOAD,
                    parameters={
                        "platform": platform_code,
                        "author": author_uid,
                        "content_id": content_id,
                        "plugin_domain": parse_result.parser,
                        "media_index": idx,
                        "media": media.model_dump(mode="json"),
                    },
                    depends_on_id=parse_subtask.id
                )
                
                if download_subtask:
                    download_subtasks.append(download_subtask)
                else:
                    logger.warning(f"[{task.task_id}] Failed to create download sub task for media {idx}")
            
            # Execute downloads with concurrency control
            if not download_subtasks:
                logger.warning(f"[{task.task_id}] No download sub tasks created")
                return self._build_task_result(
                    task_id=task.task_id,
                    parse_result_id=parse_result_id,
                    parse_subtask=parse_subtask,
                    media_count=media_count,
                    download_subtasks=[],
                    success_downloads=[],
                    failed_downloads=[],
                    saved_media_count=0,
                    saved_media_ids=[]
                )
            
            logger.info(f"[{task.task_id}] Executing {len(download_subtasks)}/{media_count} downloads")
            
            MAX_CONCURRENT_DOWNLOADS = 5
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
            
            async def download_with_semaphore(subtask):
                async with semaphore:
                    return await self._execute_media_download_sub_task(subtask)
            
            download_results = await asyncio.gather(
                *[download_with_semaphore(subtask) for subtask in download_subtasks],
                return_exceptions=False  # Let exceptions bubble up for proper handling
            )
            
            # ========== Phase 5: Process Download Results ==========
            success_downloads, failed_downloads = self._categorize_download_results(
                task_id=task.task_id,
                download_results=download_results,
                download_subtasks=download_subtasks
            )
            
            logger.info(f"[{task.task_id}] Download phase completed: {len(success_downloads)} succeeded, {len(failed_downloads)} failed")
            
            # ========== Phase 6: Save Downloaded Media ==========
            saved_media_ids = []
            saved_media_count = 0
            
            try:
                if download_results:
                    with ContentDAO() as content_dao:
                        saved_media_ids = content_dao.save_downloaded_medias(download_results, commit=True)
                        saved_media_count = len(saved_media_ids)
            except Exception as e:
                logger.exception(f"[{task.task_id}] Failed to save media records")
                # Don't raise here - parse result is already saved, partial success
            
            # ========== Phase 7: Build and Return Result ==========
            result = self._build_task_result(
                task_id=task.task_id,
                parse_result_id=parse_result_id,
                parse_subtask=parse_subtask,
                media_count=media_count,
                download_subtasks=download_subtasks,
                success_downloads=success_downloads,
                failed_downloads=failed_downloads,
                saved_media_count=saved_media_count,
                saved_media_ids=saved_media_ids
            )
            
            logger.info(f"[{task.task_id}] Parse content task completed: parse_result_id={parse_result_id}, "
                       f"media={media_count}, downloaded={len(success_downloads)}, "
                       f"failed={len(failed_downloads)}, saved={saved_media_count}")
            
            return result
            
        except Exception as e:
            logger.exception(f"[{task.task_id}] Parse content task failed")
            logger.debug(f"[{task.task_id}] Failure context: parse_result_id={parse_result_id}, "
                        f"parse_subtask={'created' if parse_subtask else 'not created'}, "
                        f"download_subtasks={len(download_subtasks)}")
            raise
    
    def _categorize_download_results(
        self,
        task_id: str,
        download_results: List[DownloadedMediaInfo],
        download_subtasks: List[SubTaskEntity]
    ) -> tuple[List[DownloadedMediaInfo], List[Dict[str, Any]]]:
        """
        Categorize download results into successful and failed downloads.
        
        Args:
            task_id: Main task ID for logging
            download_results: List of download results
            download_subtasks: List of download sub tasks
        
        Returns:
            Tuple of (success_downloads, failed_downloads)
        """
        success_downloads: List[DownloadedMediaInfo] = []
        failed_downloads: List[Dict[str, Any]] = []
        
        for idx, result in enumerate(download_results):
            subtask_id = download_subtasks[idx].sub_task_id if idx < len(download_subtasks) else None
            
            if result.status == MediaStatus.COMPLETED:
                success_downloads.append(result)
            elif result.status == MediaStatus.FAILED:
                logger.warning(f"[{task_id}] Download [{idx+1}/{len(download_results)}] failed: {subtask_id} - {result.url}")
                failed_downloads.append({
                    "index": idx,
                    "subtask_id": subtask_id,
                    "media_url": str(result.url),
                    "error": "Download failed"
                })
            else:
                logger.warning(f"[{task_id}] Download [{idx+1}/{len(download_results)}] unexpected status: {result.status}")
                failed_downloads.append({
                    "index": idx,
                    "subtask_id": subtask_id,
                    "media_url": str(result.url),
                    "error": f"Unexpected status: {result.status}"
                })
        
        return success_downloads, failed_downloads
    
    def _build_task_result(
        self,
        task_id: str,
        parse_result_id: Optional[int],
        parse_subtask: Optional[SubTaskEntity],
        media_count: int,
        download_subtasks: List[SubTaskEntity],
        success_downloads: List[DownloadedMediaInfo],
        failed_downloads: List[Dict[str, Any]],
        saved_media_count: int = 0,
        saved_media_ids: List[int] = []
    ) -> Dict[str, Any]:
        """
        Build comprehensive task result dictionary.
        
        Args:
            task_id: Main task ID
            parse_result_id: Saved parse result ID
            parse_subtask: Parse sub task entity
            media_count: Total media count from parse result
            download_subtasks: List of download sub tasks
            success_downloads: List of successfully downloaded media
            failed_downloads: List of failed download details
            saved_media_count: Number of media records saved to database
            saved_media_ids: List of saved media IDs
        
        Returns:
            Task result dictionary
        """
        return {
            "parse_result_id": parse_result_id,
            "media_count": media_count,
            "downloaded_count": len(success_downloads),
            "saved_count": saved_media_count,
            "saved_media_ids": saved_media_ids if saved_media_ids else [],
            "failed_count": len(failed_downloads),
            "failed_details": failed_downloads[:10] if failed_downloads else [],  # Limit to first 10 failures
            "subtasks": {
                "total": (1 if parse_subtask else 0) + len(download_subtasks),
                "parse_subtask_id": parse_subtask.id if parse_subtask else None,
                "download_subtask_ids": [st.id for st in download_subtasks],
                "download_count": len(download_subtasks),
                "completed": len(success_downloads),
                "failed": len(failed_downloads)
            },
            "success": parse_result_id is not None and len(failed_downloads) < media_count
        }

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
            # Extract parameters
            url = sub_task.parameters.get("url")
            plugin_id = sub_task.parameters.get("plugin_id")
            
            if not url:
                raise ValueError("URL parameter is required")
            
            # Get main task to get user_id
            main_task = self.get_main_task(sub_task.main_task_id)
            if not main_task:
                raise ValueError(f"Main task {sub_task.main_task_id} not found")

            # Update sub task status to RUNNING
            self.update_sub_task_status(sub_task.id, TaskStatus.RUNNING)

            # Parse content
            parse_result = await content_service.parser_content(
                url=url,
                plugin_id=plugin_id
            )
            
            if not parse_result:
                raise ValueError(f"Failed to parse content from URL: {url}")
            
            # Update sub task status to COMPLETED
            self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
            
            # Save sub task result
            result_data = {
                "status": "success",
                "platform": parse_result.platform.code if parse_result.platform else None,
                "author": parse_result.author.username if parse_result.author else None,
                "content_id": parse_result.pid,
                "media_count": len(parse_result.media) if parse_result.media else 0,
                "url": str(parse_result.url) if parse_result.url else None
            }
            self.update_sub_task_result(sub_task.id, result_data)
            return parse_result
            
        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Parse sub task {sub_task.sub_task_id} failed")
            
            # Update sub task status to FAILED
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            self.update_sub_task_result(sub_task.id, {
                "status": "failed",
                "error": error_msg
            })
            
            # Re-raise exception to propagate to main task
            raise

    async def _execute_media_download_sub_task(self, sub_task: SubTaskEntity) -> DownloadedMediaInfo:
        """
        Execute a media download sub task.
        Downloads a single media file and updates the database.

        Args:
            sub_task: SubTaskEntity object

        Returns:
            DownloadedMediaInfo with status indicating success or failure
        """
        # Extract parameters
        platform = sub_task.parameters.get("platform")
        author = sub_task.parameters.get("author")
        content_id = sub_task.parameters.get("content_id")
        plugin_domain = sub_task.parameters.get("plugin_domain")
        media_index = sub_task.parameters.get("media_index", 0)
        media_data = sub_task.parameters.get("media", {})

        try:
            # Validate required parameters
            if not platform or not author or not content_id:
                raise ValueError("platform, author, and content_id parameters are required")

            media = ParserMediaInfo.model_validate(media_data)

            # Get main task to get user_id
            main_task = self.get_main_task(sub_task.main_task_id)
            if not main_task:
                raise ValueError(f"Main task {sub_task.main_task_id} not found")

            # Update sub task status to RUNNING
            self.update_sub_task_status(sub_task.id, TaskStatus.RUNNING)

            # Download media — MediaService decides whether to use plugin or built-in downloader
            result = await media_service.download_media(
                platform=platform,
                author=author,
                content_id=content_id,
                media=media,
                media_index=media_index,
                plugin_domain=plugin_domain,
            )

            # Update sub task status to COMPLETED
            self.update_sub_task_status(sub_task.id, TaskStatus.COMPLETED)
            self.update_sub_task_result(sub_task.id, {
                "status": "success",
                "media_path": result.media_path if result else None
            })

            # If download_single_media returns None, treat as failure
            if result is None:
                logger.warning(f"Media download sub task {sub_task.sub_task_id} returned None")
                return DownloadedMediaInfo(
                    status=MediaStatus.FAILED,
                    url=media.url,
                    type=media.type,
                    title=media.title,
                    cover=media.cover,
                    url_fallbacks=media.url_fallbacks or [],
                    cover_fallbacks=media.cover_fallbacks or [],
                    duration=media.duration,
                    width=media.width,
                    height=media.height,
                    media_path=None,
                    cover_path=None
                )

            return result

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"Media download sub task {sub_task.sub_task_id} failed")

            # Update sub task status to FAILED
            self.update_sub_task_status(sub_task.id, TaskStatus.FAILED, error_message=error_msg)
            self.update_sub_task_result(sub_task.id, {
                "status": "failed",
                "error": error_msg
            })

            # Return a failed DownloadedMediaInfo object instead of raising exception
            _url = media_data.get("url", "https://unknown.url")
            return DownloadedMediaInfo(
                status=MediaStatus.FAILED,
                url=_url,
                type=media_data.get("type"),
                title=media_data.get("title"),
                cover=media_data.get("cover"),
                url_fallbacks=media_data.get("url_fallbacks") or [],
                cover_fallbacks=media_data.get("cover_fallbacks") or [],
                duration=media_data.get("duration"),
                width=media_data.get("width"),
                height=media_data.get("height"),
                media_path=None,
                cover_path=None
            )

    async def _execute_content_analysis_sub_task(self, sub_task: SubTaskEntity) -> Dict[str, Any]:
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
        result = {
            "status": "completed",
            "sub_task_id": sub_task.sub_task_id,
            "task_type": sub_task.type.value,
            "parameters": sub_task.parameters,
            "message": "Content analysis sub task placeholder - implementation pending"
        }
        
        return result

    # Task Management Methods

    def cancel_main_task(self, id: int) -> bool:
        """
        Cancel a main task and all its sub tasks.

        Args:
            id: Database ID of the task

        Returns:
            True if cancelled successfully
        """
        try:
            task = self.get_main_task(id)
            if not task:
                raise ValueError(f"Main task {id} not found")

            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED]:
                logger.warning(f"Cannot cancel task {id} in state {task.status}")
                return False

            # Cancel all sub tasks
            sub_tasks = self.get_sub_tasks_by_main_task(id)
            for sub_task in sub_tasks:
                if sub_task.status not in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED]:
                    self.update_sub_task_status(sub_task.id, TaskStatus.CANCELED)

            # Cancel main task
            self.update_main_task_status(id, TaskStatus.CANCELED)
            logger.info(f"Cancelled main task {id} and {len(sub_tasks)} sub tasks")
            return True

        except Exception as e:
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

        except Exception as e:
            logger.exception(f"Failed to retry main task {id}")
            raise

    # Task Monitoring and Completion

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
                linked_tasks, _ = dao.list_main_tasks(
                    task_type=TaskType.PARSE_CONTENT,
                    role=TaskRole.LINKED,
                    status=TaskStatus.PENDING,
                    limit=1000
                )

            # Filter tasks that are waiting for this specific primary task
            waiting_tasks = [task for task in linked_tasks if task.primary_task_id == primary_task_id]

            if not waiting_tasks:
                logger.debug(f"No linked tasks waiting for primary task {primary_task_id}")
                return

            logger.info(f"Completing {len(waiting_tasks)} linked tasks for primary task {primary_task_id}")

            # Complete all linked tasks with the same result
            for linked_task in waiting_tasks:
                try:
                    with TaskDAO() as dao:
                        # Update status to completed
                        dao.update_main_task_status(
                            linked_task.id,
                            TaskStatus.COMPLETED,
                            commit=False
                        )
                        # Copy result from primary task
                        dao.update_main_task_result(
                            linked_task.id,
                            {
                                **(primary_task.result or {}),
                                "linked_to": primary_task_id,
                                "linked": True
                            },
                            commit=True
                        )
                    logger.debug(f"Completed linked task {linked_task.task_id} (ID: {linked_task.id})")
                except Exception as e:
                    logger.exception(f"Failed to complete linked task {linked_task.id}")

        except Exception as e:
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
                logger.warning(f"Primary task {primary_task_id} is not failed or canceled (status: {primary_task.status})")
                return

            # Find all linked tasks waiting for this primary task
            with TaskDAO() as dao:
                linked_tasks, _ = dao.list_main_tasks(
                    task_type=TaskType.PARSE_CONTENT,
                    role=TaskRole.LINKED,
                    status=TaskStatus.PENDING,
                    limit=1000
                )

            # Filter tasks that are waiting for this specific primary task
            waiting_tasks = [task for task in linked_tasks if task.primary_task_id == primary_task_id]

            if not waiting_tasks:
                logger.debug(f"No linked tasks waiting for primary task {primary_task_id}")
                return

            logger.info(f"Marking {len(waiting_tasks)} linked tasks as {primary_task.status.value} for primary task {primary_task_id}")

            # Mark all linked tasks with the same status and error
            for linked_task in waiting_tasks:
                try:
                    error_message = f"Primary task failed: {primary_task.error_message}" if primary_task.error_message else "Primary task failed"
                    
                    with TaskDAO() as dao:
                        dao.update_main_task_status(
                            linked_task.id,
                            primary_task.status,  # Use the same status as primary (FAILED or CANCELED)
                            error_message=error_message,
                            commit=True
                        )
                    logger.debug(f"Marked linked task {linked_task.task_id} (ID: {linked_task.id}) as {primary_task.status.value}")
                except Exception as e:
                    logger.exception(f"Failed to update linked task {linked_task.id}")

        except Exception as e:
            logger.exception(f"Failed to fail linked tasks for primary {primary_task_id}")


# Singleton instance
task_service = TaskService()