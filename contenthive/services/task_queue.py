"""
Task queue service for managing task execution queue.
"""

import asyncio
from typing import Optional, Dict, Any
from collections import deque
from datetime import datetime

from contenthive.logger import logger
from contenthive.models.enumerates import TaskRole


class TaskQueue:
    """
    Task queue manager for sequential task execution.
    """
    
    def __init__(self, max_concurrent: int = 3):
        """
        Initialize task queue.
        
        Args:
            max_concurrent: Maximum number of concurrent tasks
        """
        self._queue: deque = deque()
        self._running_tasks: Dict[int, asyncio.Task] = {}
        self._max_concurrent = max_concurrent
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
    async def start(self):
        """Start the queue worker."""
        if self._worker_task is None or self._worker_task.done():
            self._shutdown = False
            self._worker_task = asyncio.create_task(self._worker())
            logger.info(f"Task queue worker started (max_concurrent={self._max_concurrent})")
    
    async def stop(self):
        """Stop the queue worker gracefully."""
        self._shutdown = True
        if self._worker_task:
            await self._worker_task
        # Wait for running tasks to complete
        if self._running_tasks:
            results = await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
            # Log any exceptions from running tasks
            for task_id, result in zip(list(self._running_tasks.keys()), results):
                if isinstance(result, Exception):
                    logger.error(f"Task {task_id} failed during shutdown: {result}")
            self._running_tasks.clear()
        logger.info("Task queue worker stopped")
    
    def enqueue(self, task_id: int, priority: int = 0) -> bool:
        """
        Add a task to the queue.
        
        Args:
            task_id: Database ID of the task
            priority: Task priority (higher = more important)
            
        Returns:
            True if enqueued successfully
        """
        try:
            # Check if task is already in queue or running
            if any(item[0] == task_id for item in self._queue):
                logger.warning(f"Task {task_id} is already in queue")
                return False
            
            if task_id in self._running_tasks:
                logger.warning(f"Task {task_id} is already running")
                return False
            
            # Add to queue with priority
            self._queue.append((task_id, priority, datetime.now()))
            # Sort by priority (descending) and timestamp (ascending)
            self._queue = deque(sorted(self._queue, key=lambda x: (-x[1], x[2])))
            
            logger.info(f"Task {task_id} enqueued (priority={priority}, queue_size={len(self._queue)})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue task {task_id}: {e}")
            return False
    
    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status.
        
        Returns:
            Queue status information
        """
        return {
            "queue_size": len(self._queue),
            "running_count": len(self._running_tasks),
            "max_concurrent": self._max_concurrent,
            "queued_tasks": [item[0] for item in self._queue],
            "running_tasks": list(self._running_tasks.keys())
        }
    
    def _task_done_callback(self, task_id: int, task: asyncio.Task):
        """Callback to handle task completion and consume exceptions."""
        try:
            # Retrieve exception/result to prevent "Task exception was never retrieved" warnings
            exception = task.exception()
            if exception:
                # Exception already logged in _execute_task, but we consume it here
                pass
        except asyncio.CancelledError:
            logger.warning(f"Task {task_id} was cancelled")
        except Exception as e:
            logger.error(f"Unexpected error retrieving task {task_id} result: {e}")
    
    async def _worker(self):
        """Background worker that processes tasks from the queue."""
        logger.info("Task queue worker started processing")
        
        while not self._shutdown:
            try:
                # Clean up completed tasks
                completed = [tid for tid, task in self._running_tasks.items() if task.done()]
                for tid in completed:
                    task = self._running_tasks[tid]
                    # Consume exception/result before deleting to prevent warnings
                    try:
                        exception = task.exception()
                        if exception:
                            # Exception already logged in _execute_task
                            pass
                    except asyncio.CancelledError:
                        logger.warning(f"Task {tid} was cancelled")
                    except Exception as e:
                        logger.error(f"Unexpected error retrieving task {tid} result: {e}")
                    finally:
                        del self._running_tasks[tid]
                
                # Check if we can start more tasks
                while len(self._running_tasks) < self._max_concurrent and self._queue:
                    task_id, priority, enqueued_at = self._queue.popleft()
                    
                    logger.info(f"Starting task {task_id} from queue (priority={priority}, "
                              f"waiting_time={(datetime.now() - enqueued_at).total_seconds():.1f}s)")
                    
                    # Create task for execution
                    task = asyncio.create_task(self._execute_task(task_id))
                    # Add done callback to consume exceptions
                    task.add_done_callback(lambda t, tid=task_id: self._task_done_callback(tid, t))
                    self._running_tasks[task_id] = task
                
                # Wait a bit before next iteration
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Task queue worker error: {e}")
                await asyncio.sleep(5)  # Wait longer on error
        
        logger.info("Task queue worker stopped processing")
    
    async def _execute_task(self, task_id: int):
        """
        Execute a single task.
        
        Args:
            task_id: Database ID of the task
        """
        from contenthive.services.task import task_service
        
        try:
            logger.info(f"Executing task {task_id}")
            result = await task_service.execute_main_task(task_id)
            
            # If this was a PRIMARY task, complete all linked tasks
            task = task_service.get_main_task(task_id)
            if task and task.role == TaskRole.PRIMARY:
                await task_service.monitor_and_complete_linked_tasks(task_id)
            
            logger.info(f"Task {task_id} completed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Task {task_id} execution failed: {e}")
            
            # If this was a PRIMARY task, mark all linked tasks as failed
            try:
                task = task_service.get_main_task(task_id)
                if task and task.role == TaskRole.PRIMARY:
                    await task_service.fail_linked_tasks(task_id)
            except Exception as linked_error:
                logger.error(f"Failed to update linked tasks for failed primary task {task_id}: {linked_error}")
            
            raise


# Global task queue instance
task_queue = TaskQueue(max_concurrent=3)