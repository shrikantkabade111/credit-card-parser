# app/schemas.py

import uuid
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Dict, Any
from datetime import date, datetime
from decimal import Decimal


class ExtractedData(BaseModel):
    """
    Standardized schema for extracted statement data.
    Enhanced with validation and metadata support.
    """
    statement_end_date: Optional[date] = None
    payment_due_date: Optional[date] = None
    total_balance: Optional[float] = Field(None, ge=0, description="Total balance in dollars")
    min_payment_due: Optional[float] = Field(None, ge=0, description="Minimum payment in dollars")
    card_last_4_digits: Optional[str] = Field(None, min_length=4, max_length=4, pattern=r'^\d{4}$')
    
    # Metadata from parser
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Parser metadata including confidence scores"
    )
    
    @field_validator('card_last_4_digits')
    @classmethod
    def validate_card_digits(cls, v):
        if v and not v.isdigit():
            raise ValueError('Card digits must be numeric')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "statement_end_date": "2025-01-15",
                "payment_due_date": "2025-02-10",
                "total_balance": 1234.56,
                "min_payment_due": 35.00,
                "card_last_4_digits": "1234",
                "metadata": {
                    "provider": "Amex",
                    "confidence_scores": {
                        "statement_end_date": 0.95,
                        "payment_due_date": 0.95,
                        "total_balance": 0.95,
                        "min_payment_due": 0.95,
                        "card_last_4_digits": 0.85
                    }
                }
            }
        }


class TaskBase(BaseModel):
    """Base schema for task-related responses."""
    task_id: uuid.UUID = Field(..., description="The unique ID for the parsing task")


class TaskCreateResponse(TaskBase):
    """Response model when a task is successfully created."""
    status: Literal["PENDING"] = "PENDING"
    detail: str = "Parsing task accepted and queued."
    estimated_time_seconds: int = Field(
        default=30,
        description="Estimated processing time in seconds"
    )


class TaskStatusResponse(TaskBase):
    """
    Response model for checking the status of a parsing task.
    Enhanced with timestamps and processing metrics.
    """
    status: Literal["PENDING", "PROCESSING", "SUCCESS", "FAILED"]
    provider_identified: Optional[str] = None
    data: Optional[ExtractedData] = None
    error: Optional[str] = Field(None, description="Error message if the task failed")
    
    # Timestamps
    created_at: Optional[datetime] = Field(None, description="Task creation time")
    started_at: Optional[datetime] = Field(None, description="Task start time")
    completed_at: Optional[datetime] = Field(None, description="Task completion time")
    
    # Processing info
    processing_time_ms: Optional[int] = Field(None, description="Processing time in milliseconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "123e4567-e89b-12d3-a456-426614174000",
                "status": "SUCCESS",
                "provider_identified": "Amex",
                "data": {
                    "statement_end_date": "2025-01-15",
                    "payment_due_date": "2025-02-10",
                    "total_balance": 1234.56,
                    "min_payment_due": 35.00,
                    "card_last_4_digits": "1234"
                },
                "error": None,
                "processing_time_ms": 1234
            }
        }


class HealthCheckResponse(BaseModel):
    """Health check response schema."""
    status: Literal["healthy", "unhealthy"]
    version: str
    environment: str
    celery_broker_connected: bool
    timestamp: datetime = Field(default_factory=datetime.now)
