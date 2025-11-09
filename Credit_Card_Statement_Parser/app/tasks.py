# app/tasks.py

from celery import Celery, Task
from celery.signals import task_prerun, task_postrun, task_failure
from app.config import settings
import logging
import time
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Celery with explicit includes
celery_app = Celery(
    'credit_card_parser',  # Give it a proper app name
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=['app.tasks']  # CRITICAL: Explicitly include tasks module
)

celery_app.conf.update(
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    result_expires=3600,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC',
    enable_utc=True,
)


# Task monitoring signals
@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Log when task starts."""
    logger.info(f"[Task {task_id}] Starting: {task.name}")


@task_postrun.connect
def task_postrun_handler(task_id, task, *args, **kwargs):
    """Log when task completes."""
    logger.info(f"[Task {task_id}] Completed: {task.name}")


@task_failure.connect
def task_failure_handler(task_id, exception, *args, **kwargs):
    """Log when task fails."""
    logger.error(f"[Task {task_id}] Failed with exception: {exception}")


class ParseStatementTask(Task):
    """Custom task class with error handling."""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        logger.error(
            f"[Task {task_id}] Task failed: {exc}",
            exc_info=einfo
        )


# CRITICAL FIX: Use explicit name matching what's sent from main.py
@celery_app.task(
    bind=True,
    base=ParseStatementTask,
    name='app.tasks.parse_statement_task',  # Full module path
    max_retries=3,
    default_retry_delay=60
)
def parse_statement_task(self, file_contents: bytes) -> dict:
    """
    Celery background task to parse a credit card statement.
    
    Args:
        file_contents: PDF file content as bytes
    
    Returns:
        dict: TaskStatusResponse as dictionary
    """
    # Import here to avoid circular imports
    from app.parsing.main_parser import ParserOrchestrator
    from app.schemas import TaskStatusResponse
    
    task_id = self.request.id
    start_time = time.time()
    created_at = datetime.now()
    
    logger.info(f"[Task {task_id}] Processing PDF ({len(file_contents)} bytes)")
    
    try:
        orchestrator = ParserOrchestrator(pdf_content=file_contents)
        started_at = datetime.now()
        
        provider_name, extracted_data = orchestrator.run_parsing(task_id=str(task_id))
        
        completed_at = datetime.now()
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        logger.info(
            f"[Task {task_id}] Successfully parsed. "
            f"Provider: {provider_name}, "
            f"Time: {processing_time_ms}ms"
        )
        
        result = TaskStatusResponse(
            task_id=task_id,
            status="SUCCESS",
            provider_identified=provider_name,
            data=extracted_data,
            error=None,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            processing_time_ms=processing_time_ms
        )
        
        # --- FIX 1: Use mode='json' to serialize dates to strings ---
        return result.model_dump(mode='json')
    
    except ValueError as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.warning(f"[Task {task_id}] Parsing failed: {e}")
        
        result = TaskStatusResponse(
            task_id=task_id,
            status="FAILED",
            provider_identified=None,
            data=None,
            error=str(e),
            created_at=created_at,
            processing_time_ms=processing_time_ms
        )
        
        # --- FIX 2: Use mode='json' to serialize dates to strings ---
        return result.model_dump(mode='json')
    
    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[Task {task_id}] Unexpected error: {e}", exc_info=True)
        
        # Retry on unexpected errors
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            result = TaskStatusResponse(
                task_id=task_id,
                status="FAILED",
                provider_identified=None,
                data=None,
                error=f"Max retries exceeded. Last error: {str(e)}",
                created_at=created_at,
                processing_time_ms=processing_time_ms
            )
            # --- FIX 3: Use mode='json' to serialize dates to strings ---
            return result.model_dump(mode='json')