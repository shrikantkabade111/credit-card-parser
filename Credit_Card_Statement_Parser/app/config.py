# app/config.py

"""
Production-ready configuration for the Credit Card Statement Parsing Microservice.
Compatible with Pydantic v2.x (requires `pydantic-settings` package).
"""

import logging
from functools import lru_cache
from pydantic import Field, field_validator  # Changed from validator
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    # -----------------------------------------------------------------------------
    # Core Service Configuration
    # -----------------------------------------------------------------------------
    PROJECT_NAME: str = Field("Credit Card Statement Parser", env="PROJECT_NAME")
    VERSION: str = Field("1.0.0", env="PROJECT_VERSION")
    ENVIRONMENT: str = Field("development", env="ENVIRONMENT")
    DEBUG: bool = Field(False, env="DEBUG")

    # -----------------------------------------------------------------------------
    # Security & Authentication
    # -----------------------------------------------------------------------------
    # FIXED: Changed API_KEY to MASTER_API_KEY to match security.py
    MASTER_API_KEY: str = Field(
        "dev-api-key", 
        env="MASTER_API_KEY",
        description="Master API key for authentication"
    )
    API_KEY_HEADER_NAME: str = Field("X-API-Key", env="API_KEY_HEADER_NAME")

    # -----------------------------------------------------------------------------
    # File Upload Configuration
    # -----------------------------------------------------------------------------
    MAX_UPLOAD_SIZE_MB: int = Field(5, env="MAX_UPLOAD_SIZE_MB")
    ALLOWED_FILE_TYPES: List[str] = ["application/pdf"]

    # -----------------------------------------------------------------------------
    # Celery / Redis Configuration
    # -----------------------------------------------------------------------------
    CELERY_BROKER_URL: str = Field("redis://redis:6379/0", env="CELERY_BROKER_URL")
    CELERY_RESULT_BACKEND: str = Field("redis://redis:6379/0", env="CELERY_RESULT_BACKEND")
    CELERY_TASK_TIME_LIMIT: int = Field(300, env="CELERY_TASK_TIME_LIMIT")
    CELERY_TASK_SOFT_TIME_LIMIT: int = Field(240, env="CELERY_TASK_SOFT_TIME_LIMIT")

    # -----------------------------------------------------------------------------
    # OCR / Tesseract Configuration
    # -----------------------------------------------------------------------------
    TESSERACT_OCR_ENABLED: bool = Field(True, env="TESSERACT_OCR_ENABLED")
    TESSERACT_PATH: Optional[str] = Field(None, env="TESSERACT_PATH")
    OCR_LANGUAGE: str = Field("eng", env="OCR_LANGUAGE")
    OCR_TESSERACT_CONFIG: str = Field("--psm 6", env="OCR_TESSERACT_CONFIG")

    # -----------------------------------------------------------------------------
    # S3 / Storage
    # -----------------------------------------------------------------------------
    S3_ENABLED: bool = Field(False, env="S3_ENABLED")
    S3_BUCKET_NAME: Optional[str] = Field(None, env="S3_BUCKET_NAME")
    S3_REGION: Optional[str] = Field(None, env="S3_REGION")
    S3_ACCESS_KEY_ID: Optional[str] = Field(None, env="S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY: Optional[str] = Field(None, env="S3_SECRET_ACCESS_KEY")
    S3_ENDPOINT_URL: Optional[str] = Field(None, env="S3_ENDPOINT_URL")

    # -----------------------------------------------------------------------------
    # Sentry Monitoring
    # -----------------------------------------------------------------------------
    SENTRY_DSN: Optional[str] = Field(None, env="SENTRY_DSN")

    # -----------------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------------
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")

    # -----------------------------------------------------------------------------
    # CORS
    # -----------------------------------------------------------------------------
    ALLOWED_ORIGINS: List[str] = Field(["*"], env="ALLOWED_ORIGINS")

    # -----------------------------------------------------------------------------
    # API Routes
    # -----------------------------------------------------------------------------
    API_V1_STR: str = Field("/api/v1", env="API_V1_STR")

    # -----------------------------------------------------------------------------
    # Security / Rate Limiting
    # -----------------------------------------------------------------------------
    RATE_LIMIT_PER_MINUTE: int = Field(60, env="RATE_LIMIT_PER_MINUTE")

    # -----------------------------------------------------------------------------
    # Validators (Pydantic v2 syntax)
    # -----------------------------------------------------------------------------
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate and set log level."""
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        level = v.upper()
        if level not in allowed:
            raise ValueError(f"Invalid LOG_LEVEL: {v}. Must be one of {allowed}")
        return level

    @field_validator("MAX_UPLOAD_SIZE_MB")
    @classmethod
    def validate_upload_size(cls, v: int) -> int:
        """Validate upload size is reasonable."""
        if v <= 0 or v > 100:
            raise ValueError("MAX_UPLOAD_SIZE_MB must be between 1 and 100")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables


# -----------------------------------------------------------------------------
# Cached instance (singleton)
# -----------------------------------------------------------------------------
@lru_cache()
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
