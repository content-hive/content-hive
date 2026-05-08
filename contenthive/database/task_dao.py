from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session, joinedload

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import MainTask, SubTask
from contenthive.logger import logger
from contenthive.models.enumerates import TaskRole, TaskStatus, TaskType
from contenthive.models.task import MainTaskEntity, SubTaskEntity


class TaskDAO:
    """
    Data Access Object for task-related database operations.
    """

    def __init__(self):
        self.engine = get_engine()
        self.SessionLocal = get_session_local()
        self.session = None

    def __enter__(self):
        self.session = self.SessionLocal()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_session(self) -> Session:
        """Get database session"""
        if self.session is None:
            self.session = self.SessionLocal()
        return self.session

    def close(self):
        """Close database session"""
        if self.session:
            self.session.close()
            self.session = None

    # MainTask Methods

    def create_main_task(
        self,
        task_id: str,
        user_id: int,
        task_type: TaskType,
        url: str,
        parameters: dict,
        status: TaskStatus = TaskStatus.PENDING,
        role: TaskRole | None = None,
        primary_task_id: int | None = None,
        parse_result_id: int | None = None,
        commit: bool = True,
    ) -> int:
        """
        Create a new main task.

        Args:
            task_id: Unique task identifier
            user_id: User ID who created the task
            task_type: Type of the task
            url: Target URL for the task
            parameters: Task parameters as JSON
            status: Task status (default: PENDING)
            role: Task role (primary, linked, reused)
            primary_task_id: ID of primary task if this is linked/reused
            parse_result_id: Associated parse result ID
            commit: Whether to commit immediately (default: True)

        Returns:
            Created task's database ID
        """
        session = self._get_session()
        try:
            main_task = MainTask(
                task_id=task_id,
                user_id=user_id,
                type=task_type,
                status=status,
                role=role,
                url=url,
                parameters=parameters,
                primary_task_id=primary_task_id,
                parse_result_id=parse_result_id,
            )
            session.add(main_task)
            session.flush()
            task_db_id = main_task.id

            if commit:
                session.commit()

            return task_db_id
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to create main task {task_id}")
            raise

    def create_reused_main_task(
        self,
        task_id: str,
        user_id: int,
        task_type: TaskType,
        url: str,
        parameters: dict,
        parse_result_id: int,
        commit: bool = True,
    ) -> int:
        """
        Create a REUSED main task that's already completed.
        This task instantly returns historical results without execution.

        Args:
            task_id: Unique task identifier
            user_id: User ID who created the task
            task_type: Type of the task
            url: Target URL for the task
            parameters: Task parameters as JSON
            parse_result_id: Associated parse result ID
            commit: Whether to commit immediately (default: True)

        Returns:
            Created task's database ID
        """
        session = self._get_session()
        try:
            now = datetime.now(UTC)

            main_task = MainTask(
                task_id=task_id,
                user_id=user_id,
                type=task_type,
                status=TaskStatus.COMPLETED,
                role=TaskRole.REUSED,
                url=url,
                parameters=parameters,
                primary_task_id=None,
                parse_result_id=parse_result_id,
                started_at=now,
                completed_at=now,
                result={"parse_result_id": parse_result_id, "reused": True},
            )
            session.add(main_task)
            session.flush()
            task_db_id = main_task.id

            if commit:
                session.commit()

            return task_db_id
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to create REUSED main task {task_id}")
            raise

    def get_main_task_by_id(self, id: int, include_sub_tasks: bool = False) -> MainTaskEntity | None:
        """
        Get main task by database ID.

        Args:
            id: Database ID of the task
            include_sub_tasks: Whether to load sub tasks

        Returns:
            MainTaskEntity object or None
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.id == id)

            if include_sub_tasks:
                stmt = stmt.options(joinedload(MainTask.sub_tasks))

            result = session.execute(stmt).unique().scalar_one_or_none()
            return MainTaskEntity.from_orm(result) if result else None
        except Exception:
            logger.exception(f"Failed to get main task by ID {id}")
            raise

    def get_main_task_by_task_id(self, task_id: str, include_sub_tasks: bool = False) -> MainTaskEntity | None:
        """
        Get main task by task ID string.

        Args:
            task_id: Unique task identifier
            include_sub_tasks: Whether to load sub tasks

        Returns:
            MainTaskEntity object or None
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.task_id == task_id)

            if include_sub_tasks:
                stmt = stmt.options(joinedload(MainTask.sub_tasks))

            result = session.execute(stmt).unique().scalar_one_or_none()
            return MainTaskEntity.from_orm(result) if result else None
        except Exception:
            logger.exception(f"Failed to get main task by task_id {task_id}")
            raise

    def update_main_task_status(
        self,
        id: int,
        status: TaskStatus,
        error_message: str | None = None,
        commit: bool = True,
    ) -> bool:
        """
        Update main task status.

        Args:
            id: Database ID of the task
            status: New status
            error_message: Error message if failed
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.id == id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                logger.warning(f"Main task {id} not found")
                return False

            task.status = status

            if status == TaskStatus.RUNNING and task.started_at is None:
                task.started_at = datetime.now(UTC)

            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED]:
                task.completed_at = datetime.now(UTC)

            if error_message:
                task.error_message = error_message

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update main task {id} status")
            raise

    def update_main_task_result(self, id: int, result: dict, commit: bool = True) -> bool:
        """
        Update main task result.

        Args:
            id: Database ID of the task
            result: Task result as JSON
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.id == id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                logger.warning(f"Main task {id} not found")
                return False

            task.result = result

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update main task {id} result")
            raise

    def update_main_task_parse_result_id(self, id: int, parse_result_id: int, commit: bool = True) -> bool:
        """
        Update main task's associated parse result ID.

        Args:
            id: Database ID of the task
            parse_result_id: Parse result ID to associate
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.id == id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                logger.warning(f"Main task {id} not found")
                return False

            task.parse_result_id = parse_result_id

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update main task {id} parse_result_id")
            raise

    def bulk_update_linked_task_primary(
        self,
        task_ids: list[int],
        new_primary_id: int,
        new_primary_role: TaskRole,
    ) -> None:
        """
        Promote one linked task to PRIMARY and re-point all remaining linked tasks
        to the new primary in a single transaction (3 statements total).

        Args:
            task_ids: IDs of the remaining LINKED tasks to re-point
            new_primary_id: ID of the task being promoted to PRIMARY
            new_primary_role: Role to assign to the new primary (PRIMARY)
        """
        session = self._get_session()
        try:
            if task_ids:
                session.execute(
                    update(MainTask).where(MainTask.id.in_(task_ids)).values(primary_task_id=new_primary_id)
                )

            session.execute(
                update(MainTask)
                .where(MainTask.id == new_primary_id)
                .values(role=new_primary_role, primary_task_id=None)
            )

            session.commit()
        except Exception:
            session.rollback()
            logger.exception(f"Failed to bulk update linked tasks (new_primary={new_primary_id})")
            raise

    def list_main_tasks(
        self,
        user_id: int | None = None,
        task_type: TaskType | None = None,
        status: list[TaskStatus] | None = None,
        task_ids: list[str] | None = None,
        role: TaskRole | None = None,
        primary_task_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        include_sub_tasks: bool = False,
        sort_by: str = "created_at",
        order: str = "desc",
    ) -> tuple[list[MainTaskEntity], int]:
        """
        List main tasks with filters.

        Args:
            user_id: Filter by user ID
            task_type: Filter by task type
            status: Filter by status. Ignored when task_ids is provided.
            task_ids: Filter by task IDs. When provided, status filter is ignored.
            role: Filter by role
            primary_task_id: Filter by primary task ID
            limit: Maximum number of results
            offset: Offset for pagination
            include_sub_tasks: Whether to load sub tasks
            sort_by: Column to sort by (id, created_at, updated_at)
            order: Sort direction (asc, desc)

        Returns:
            Tuple of (List of MainTaskEntity objects, total count)
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.deleted_at.is_(None))

            if user_id is not None:
                stmt = stmt.where(MainTask.user_id == user_id)

            if task_type is not None:
                stmt = stmt.where(MainTask.type == task_type)

            if task_ids:
                stmt = stmt.where(MainTask.task_id.in_(task_ids))
            elif status:
                stmt = stmt.where(MainTask.status.in_(status))

            if role is not None:
                stmt = stmt.where(MainTask.role == role)

            if primary_task_id is not None:
                stmt = stmt.where(MainTask.primary_task_id == primary_task_id)

            # Get total count with the same filters
            count_stmt = select(func.count(MainTask.id)).where(MainTask.deleted_at.is_(None))
            if user_id is not None:
                count_stmt = count_stmt.where(MainTask.user_id == user_id)
            if task_type is not None:
                count_stmt = count_stmt.where(MainTask.type == task_type)
            if task_ids:
                count_stmt = count_stmt.where(MainTask.task_id.in_(task_ids))
            elif status:
                count_stmt = count_stmt.where(MainTask.status.in_(status))
            if role is not None:
                count_stmt = count_stmt.where(MainTask.role == role)
            if primary_task_id is not None:
                count_stmt = count_stmt.where(MainTask.primary_task_id == primary_task_id)

            total = session.execute(count_stmt).scalar() or 0

            if include_sub_tasks:
                stmt = stmt.options(joinedload(MainTask.sub_tasks))

            sort_field_map = {
                "id": MainTask.id,
                "created_at": MainTask.created_at,
                "updated_at": MainTask.updated_at,
            }
            sort_field = sort_field_map.get(sort_by, MainTask.created_at)

            stmt = stmt.order_by(sort_field.asc()) if order.lower() == "asc" else stmt.order_by(sort_field.desc())

            stmt = stmt.limit(limit).offset(offset)

            result = session.execute(stmt).unique().scalars().all()
            return [MainTaskEntity.from_orm(task) for task in result], total
        except Exception:
            logger.exception("Failed to list main tasks")
            raise

    def find_running_primary_task_by_url(
        self, url: str, task_type: TaskType = TaskType.PARSE_CONTENT
    ) -> MainTaskEntity | None:
        """
        Find a running primary task for the given URL.
        Used for task deduplication to check if there's an ongoing primary task.

        Args:
            url: URL to search for
            task_type: Type of task (default: PARSE_CONTENT)

        Returns:
            MainTaskEntity object if found, None otherwise
        """
        session = self._get_session()
        try:
            # Query for PRIMARY tasks with matching URL using indexed url field
            stmt = select(MainTask).where(
                and_(
                    MainTask.type == task_type,
                    MainTask.role == TaskRole.PRIMARY,
                    MainTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
                    MainTask.deleted_at.is_(None),
                    MainTask.url == url,
                )
            )

            result = session.execute(stmt).scalar_one_or_none()
            return MainTaskEntity.from_orm(result) if result else None
        except Exception:
            logger.exception(f"Failed to find running primary task for URL {url}")
            raise

    def delete_main_task(self, id: int, commit: bool = True) -> bool:
        """
        Delete a main task (soft delete by default).

        Args:
            id: Database ID of the task
            commit: Whether to commit immediately (default: True)

        Returns:
            True if deleted successfully
        """
        session = self._get_session()
        try:
            stmt = select(MainTask).where(MainTask.id == id)
            task = session.execute(stmt).scalar_one_or_none()
            if not task:
                logger.warning(f"Main task {id} not found")
                return False

            task.deleted_at = datetime.now(UTC)

            if commit:
                session.commit()
                logger.debug(f"Deleted main task {id}")

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to delete main task {id}")
            raise

    # SubTask Methods

    def create_sub_task(
        self,
        sub_task_id: str,
        main_task_id: int,
        task_type: TaskType,
        parameters: dict,
        status: TaskStatus = TaskStatus.PENDING,
        depends_on_id: int | None = None,
        commit: bool = True,
    ) -> int:
        """
        Create a new sub task.

        Args:
            sub_task_id: Unique sub task identifier
            main_task_id: Parent main task ID
            task_type: Type of the sub task
            parameters: Task parameters as JSON
            status: Task status (default: PENDING)
            depends_on_id: ID of sub task this depends on
            commit: Whether to commit immediately (default: True)

        Returns:
            Created sub task's database ID
        """
        session = self._get_session()
        try:
            sub_task = SubTask(
                sub_task_id=sub_task_id,
                main_task_id=main_task_id,
                type=task_type,
                status=status,
                parameters=parameters,
                depends_on_id=depends_on_id,
                progress=0,
            )
            session.add(sub_task)
            session.flush()
            sub_task_db_id = sub_task.id

            if commit:
                session.commit()

            return sub_task_db_id
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to create sub task {sub_task_id}")
            raise

    def get_sub_task_by_id(self, id: int) -> SubTaskEntity | None:
        """
        Get sub task by database ID.

        Args:
            id: Database ID of the sub task

        Returns:
            SubTaskEntity object or None
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.id == id)
            result = session.execute(stmt).scalar_one_or_none()
            return SubTaskEntity.from_orm(result) if result else None
        except Exception:
            logger.exception(f"Failed to get sub task by ID {id}")
            raise

    def get_sub_task_by_sub_task_id(self, sub_task_id: str) -> SubTaskEntity | None:
        """
        Get sub task by sub task ID string.

        Args:
            sub_task_id: Unique sub task identifier

        Returns:
            SubTaskEntity object or None
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.sub_task_id == sub_task_id)
            result = session.execute(stmt).scalar_one_or_none()
            return SubTaskEntity.from_orm(result) if result else None
        except Exception:
            logger.exception(f"Failed to get sub task by sub_task_id {sub_task_id}")
            raise

    def get_sub_tasks_by_main_task_id(self, main_task_id: int) -> list[SubTaskEntity]:
        """
        Get all sub tasks for a main task.

        Args:
            main_task_id: Database ID of the main task

        Returns:
            List of SubTaskEntity objects
        """
        session = self._get_session()
        try:
            stmt = (
                select(SubTask)
                .where(
                    and_(
                        SubTask.main_task_id == main_task_id,
                        SubTask.deleted_at.is_(None),
                    )
                )
                .order_by(SubTask.created_at.asc())
            )

            result = session.execute(stmt).scalars().all()
            return [SubTaskEntity.from_orm(task) for task in result]
        except Exception:
            logger.exception(f"Failed to get sub tasks for main task {main_task_id}")
            raise

    def update_sub_task_status(
        self,
        id: int,
        status: TaskStatus,
        error_message: str | None = None,
        commit: bool = True,
    ) -> bool:
        """
        Update sub task status.

        Args:
            id: Database ID of the sub task
            status: New status
            error_message: Error message if failed
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.id == id)
            sub_task = session.execute(stmt).scalar_one_or_none()
            if not sub_task:
                logger.warning(f"Sub task {id} not found")
                return False

            sub_task.status = status

            if status == TaskStatus.RUNNING and sub_task.started_at is None:
                sub_task.started_at = datetime.now(UTC)

            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED]:
                sub_task.completed_at = datetime.now(UTC)
                if status == TaskStatus.COMPLETED:
                    sub_task.progress = 100

            if error_message:
                sub_task.error_message = error_message

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update sub task {id} status")
            raise

    def update_sub_task_progress(self, id: int, progress: int, commit: bool = True) -> bool:
        """
        Update sub task progress.

        Args:
            id: Database ID of the sub task
            progress: Progress percentage (0-100)
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.id == id)
            sub_task = session.execute(stmt).scalar_one_or_none()
            if not sub_task:
                logger.warning(f"Sub task {id} not found")
                return False

            # Clamp progress between 0 and 100
            sub_task.progress = max(0, min(100, progress))

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update sub task {id} progress")
            raise

    def update_sub_task_result(self, id: int, result: dict, commit: bool = True) -> bool:
        """
        Update sub task result.

        Args:
            id: Database ID of the sub task
            result: Task result as JSON
            commit: Whether to commit immediately (default: True)

        Returns:
            True if updated successfully
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.id == id)
            sub_task = session.execute(stmt).scalar_one_or_none()
            if not sub_task:
                logger.warning(f"Sub task {id} not found")
                return False

            sub_task.result = result

            if commit:
                session.commit()

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to update sub task {id} result")
            raise

    def list_sub_tasks(
        self,
        main_task_id: int | None = None,
        task_type: TaskType | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SubTaskEntity]:
        """
        List sub tasks with filters.

        Args:
            main_task_id: Filter by main task ID
            task_type: Filter by task type
            status: Filter by status
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of SubTaskEntity objects
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.deleted_at.is_(None))

            if main_task_id is not None:
                stmt = stmt.where(SubTask.main_task_id == main_task_id)

            if task_type is not None:
                stmt = stmt.where(SubTask.type == task_type)

            if status is not None:
                stmt = stmt.where(SubTask.status == status)

            stmt = stmt.order_by(SubTask.created_at.desc()).limit(limit).offset(offset)

            result = session.execute(stmt).scalars().all()
            return [SubTaskEntity.from_orm(task) for task in result]
        except Exception:
            logger.exception("Failed to list sub tasks")
            raise

    def delete_sub_task(self, id: int, soft_delete: bool = True, commit: bool = True) -> bool:
        """
        Delete a sub task (soft delete by default).

        Args:
            id: Database ID of the sub task
            soft_delete: If True, set deleted_at; if False, hard delete
            commit: Whether to commit immediately (default: True)

        Returns:
            True if deleted successfully
        """
        session = self._get_session()
        try:
            stmt = select(SubTask).where(SubTask.id == id)
            sub_task = session.execute(stmt).scalar_one_or_none()
            if not sub_task:
                logger.warning(f"Sub task {id} not found")
                return False

            if soft_delete:
                sub_task.deleted_at = datetime.now(UTC)
            else:
                session.delete(sub_task)

            if commit:
                session.commit()
                logger.debug(f"Deleted sub task {id} (soft={soft_delete})")

            return True
        except Exception:
            if commit:
                session.rollback()
            logger.exception(f"Failed to delete sub task {id}")
            raise
