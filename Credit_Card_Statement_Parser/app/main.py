# app/main.py

import uuid
import time
import json  # <-- NEW IMPORT
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response  # <-- NEW IMPORT
from celery.result import AsyncResult
from app.tasks import parse_statement_task, celery_app
from app.schemas import (
    TaskCreateResponse,
    TaskStatusResponse,
    HealthCheckResponse
)
from app.config import settings
from app.security import get_api_key
import logging
from contextlib import asynccontextmanager

# Configure logging
# Note: config.py also configures logging, this ensures it's set
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)


# Lifespan context manager for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Initialize Sentry if configured
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk
            sentry_sdk.init(
                dsn=settings.SENTRY_DSN,
                environment=settings.ENVIRONMENT,
                traces_sample_rate=0.1 if settings.ENVIRONMENT == "production" else 1.0,
            )
            logger.info("Sentry monitoring initialized")
        except ImportError:
            logger.warning("Sentry SDK not installed, skipping initialization")
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.PROJECT_NAME}")


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production-ready microservice to parse PDF credit card statements with async processing",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# Add middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests with timing."""
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    logger.info(
        f"{request.method} {request.url.path} - "
        f"Status: {response.status_code} - "
        f"Duration: {process_time:.2f}ms"
    )
    
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. Please try again later."}
    )


# Health check endpoint
@app.get(
    "/health",
    response_model=HealthCheckResponse,
    tags=["Health"],
    summary="Service Health Check"
)
async def health_check():
    """Check service health and dependencies."""
    celery_ok = False
    try:
        # Check if Celery broker is reachable
        celery_app.control.inspect().stats()
        celery_ok = True
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
    
    return HealthCheckResponse(
        status="healthy" if celery_ok else "unhealthy",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        celery_broker_connected=celery_ok
    )


@app.get("/", include_in_schema=False)
def read_root():
    """Root endpoint."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME} v{settings.VERSION}",
        "docs": "/docs" if settings.DEBUG else "disabled",
        "health": "/health"
    }


# --- API Endpoints ---

@app.post(
    f"{settings.API_V1_STR}/parse/upload",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload Statement for Parsing",
    tags=["Parsing"]
)
async def upload_statement(
    request: Request,
    file: UploadFile = File(..., description="PDF credit card statement"),
    api_key: str = Depends(get_api_key)
):
    """Upload a PDF credit card statement for asynchronous parsing."""
    
    # Validate content type
    if file.content_type not in settings.ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Invalid file type: {file.content_type}. Only PDF files are accepted."
        )
    
    try:
        file_contents = await file.read()
        
        if not file_contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty."
            )
        
        file_size_mb = len(file_contents) / (1024 * 1024)
        if file_size_mb > settings.MAX_UPLOAD_SIZE_MB:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size ({file_size_mb:.2f}MB) exceeds maximum allowed size ({settings.MAX_UPLOAD_SIZE_MB}MB)."
            )
        
        # Use the explicit task name defined in tasks.py
        task = celery_app.send_task(
            'app.tasks.parse_statement_task',
            args=[file_contents],
            task_id=str(uuid.uuid4())
        )
        
        logger.info(
            f"Task {task.id} queued for file: {file.filename} "
            f"({file_size_mb:.2f}MB) from {request.client.host}"
        )
        
        return TaskCreateResponse(
            task_id=task.id,
            estimated_time_seconds=30
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error queuing task: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue parsing task. Please try again."
        )
    finally:
        await file.close()


@app.get(
    f"{settings.API_V1_STR}/parse/status/{{task_id}}",
    response_model=TaskStatusResponse,
    summary="Check Parsing Task Status",
    tags=["Parsing"]
)
async def get_task_status(
    task_id: uuid.UUID,
    api_key: str = Depends(get_api_key)
):
    """
    Retrieve the status and result of a parsing task.
    
    Poll this endpoint with the task_id received from /upload.
    """
    
    try:
        task_result = AsyncResult(str(task_id), app=celery_app)
        
        if not task_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found."
            )
        
        # Map Celery states to our status
        state_mapping = {
            "PENDING": "PENDING",
            "STARTED": "PROCESSING",
            "SUCCESS": "SUCCESS",
            "FAILURE": "FAILED",
            "RETRY": "PROCESSING",
        }
        
        task_status = state_mapping.get(task_result.state, "PENDING")
        
        if task_status in ["PENDING", "PROCESSING"]:
            return TaskStatusResponse(
                task_id=task_id,
                status=task_status
            )
        
        elif task_status == "SUCCESS":
            result_data = task_result.result
            return TaskStatusResponse(**result_data)
        
        elif task_status == "FAILED":
            error_msg = str(task_result.info) if task_result.info else "Unknown error"
            logger.error(f"Task {task_id} failed: {error_msg}")
            
            return TaskStatusResponse(
                task_id=task_id,
                status="FAILED",
                error=error_msg
            )
        
        return TaskStatusResponse(
            task_id=task_id,
            status="FAILED",
            error=f"Unknown task state: {task_result.state}"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving task status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving task status."
        )
@app.get(
    f"{settings.API_V1_STR}/parse/download/{{task_id}}",
    summary="Download Parsing Result as JSON",
    tags=["Parsing"],
    response_class=Response
)
async def get_task_download(
    task_id: uuid.UUID,
    api_key: str = Depends(get_api_key)
):
    """
    Download the extracted data as a JSON file once the task is complete.
    """
    try:
        task_result = AsyncResult(str(task_id), app=celery_app)
        
        if not task_result or task_result.state in ["PENDING", "STARTED", "RETRY"]:
            # Task not found or not ready
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result not available. The task is pending, processing, or does not exist."
            )

        if task_result.state == "FAILURE":
            # Task failed
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task failed and has no result to download. Error: {task_result.info}"
            )
        
        if task_result.state == "SUCCESS":
            # Task succeeded, get the result
            result_data = task_result.result  # This is the TaskStatusResponse dict
            
            # We only want to download the 'data' part
            extracted_data = result_data.get('data')
            
            if extracted_data is None:
                # Handle case where parsing was successful but found no data
                extracted_data = {"message": "Parsing successful, but no data was extracted."}

            # Convert the data dict to a JSON string
            json_content = json.dumps(extracted_data, indent=2)
            
            # Create a filename
            filename = f"parsing_result_{task_id}.json"
            
            # Set headers to trigger browser download
            headers = {
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
            
            return Response(
                content=json_content,
                media_type="application/json",
                headers=headers
            )

        # Handle any other unexpected state
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task is in an unknown state: {task_result.state}"
        )

    except HTTPException:
        raise  # Re-raise known HTTP exceptions
    except Exception as e:
        logger.error(f"Error retrieving task for download: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving task result."
        )
