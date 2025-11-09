# app/security.py

"""
High-security API key authentication and thread-safe rate limiting middleware
for the Credit Card Statement Parsing microservice.

Features:
- Constant-time API key validation (HMAC)
- Thread-safe in-memory rate limiting
- Per-minute request throttling per API key
- Secure hashed logging (no raw API keys exposed)
"""

# ============================================================================
# STEP 1: Standard library imports
# ============================================================================
import hmac
import hashlib
import threading
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional

# ============================================================================
# STEP 2: Third-party imports
# ============================================================================
from fastapi import Security, HTTPException, status, Request
from fastapi.security.api_key import APIKeyHeader

# ============================================================================
# STEP 3: Local imports (AFTER logging is imported)
# ============================================================================
from app.config import settings

# ============================================================================
# STEP 4: Initialize logger (MUST be after logging import)
# ============================================================================
logger = logging.getLogger(__name__)

# ============================================================================
# STEP 5: Now you can use logger
# ============================================================================
# Debug logging for API key (optional - remove in production)
if getattr(settings, 'DEBUG', False):
    logger.info(f"Loaded MASTER_API_KEY from environment (length: {len(settings.MASTER_API_KEY) if settings.MASTER_API_KEY else 0})")

# ============================================================================
# API Key Header Configuration
# ============================================================================
API_KEY_NAME = getattr(settings, "API_KEY_HEADER_NAME", "X-API-Key")
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

# ============================================================================
# Thread-Safe In-Memory Rate Limiter
# ============================================================================
class RateLimiter:
    """
    Thread-safe token bucket rate limiter.
    Allows up to `rate_limit` requests per minute per API key.
    
    Note: For multi-instance deployments, use Redis-based rate limiting.
    """

    def __init__(self, rate_limit: int = 60):
        self.rate_limit = rate_limit
        self._requests = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is allowed; otherwise False."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)

        with self._lock:
            # Remove timestamps older than 1 minute
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]

            # Enforce rate limit
            if len(self._requests[key]) >= self.rate_limit:
                return False

            # Log current request time
            self._requests[key].append(now)
            return True
    
    def get_remaining(self, key: str) -> int:
        """Get remaining requests for a key (useful for headers)."""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        with self._lock:
            valid_requests = [t for t in self._requests[key] if t > cutoff]
            return max(0, self.rate_limit - len(valid_requests))


# Instantiate global rate limiter
rate_limiter = RateLimiter(rate_limit=getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60))

# ============================================================================
# Secure Helper Utilities
# ============================================================================
def hash_api_key(api_key: str) -> str:
    """Return a short SHA256 fingerprint of the API key for anonymized logging."""
    if not api_key:
        return "none"
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def constant_time_compare(val1: str, val2: str) -> bool:
    """Perform constant-time string comparison to prevent timing attacks."""
    if not val1 or not val2:
        return False
    return hmac.compare_digest(val1.encode(), val2.encode())


def normalize_key(key: Optional[str]) -> Optional[str]:
    """Normalize API key by removing whitespace and line breaks."""
    if not key:
        return None
    return key.strip().replace("\r", "").replace("\n", "")

# ============================================================================
# Main Dependency: get_api_key
# ============================================================================
async def get_api_key(
    request: Request,
    api_key_header_value: str = Security(api_key_header)
) -> str:
    """
    Validates the incoming API key header and applies rate limiting.

    Args:
        request: FastAPI Request object
        api_key_header_value: API key from header

    Returns:
        Validated API key string

    Raises:
        HTTPException: 401 if API key is missing or invalid
        HTTPException: 429 if rate limit exceeded
    """

    # 1️⃣ Check presence
    if not api_key_header_value:
        logger.warning(f"Missing API key from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key in header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 2️⃣ Normalize values to prevent whitespace/newline mismatch
    incoming = normalize_key(api_key_header_value)
    master_key = (
        getattr(settings, "MASTER_API_KEY", None) or 
        getattr(settings, "API_KEY", None)
    )
    cfg_key = normalize_key(master_key)

    # 🔍 DEBUG LOGGING (only in debug mode)
    if getattr(settings, 'DEBUG', False):
        logger.debug(f"Incoming API key: [{incoming[:8]}...] (len={len(incoming) if incoming else 0})")
        logger.debug(f"Expected API key: [{cfg_key[:8] if cfg_key else 'NONE'}...] (len={len(cfg_key) if cfg_key else 0})")
        logger.debug(f"Keys match: {incoming == cfg_key if incoming and cfg_key else False}")

    # 3️⃣ Validate configuration
    if not cfg_key:
        logger.error("MASTER_API_KEY not configured in settings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key authentication not properly configured."
        )

    # 4️⃣ Validate using constant-time comparison
    if not incoming or not constant_time_compare(incoming, cfg_key):
        client_hash = hash_api_key(incoming or "")
        
        # Enhanced error logging
        logger.warning(
            f"Invalid API key attempt from {request.client.host} "
            f"(hash={client_hash}). "
            f"Incoming length: {len(incoming) if incoming else 0}, "
            f"Expected length: {len(cfg_key)}"
        )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 5️⃣ Apply rate limiting
    client_hash = hash_api_key(incoming)
    if not rate_limiter.is_allowed(client_hash):
        remaining = rate_limiter.get_remaining(client_hash)
        logger.warning(
            f"Rate limit exceeded for client {client_hash} "
            f"({request.client.host})"
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded. "
                f"Max {getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60)} requests per minute. "
                f"Retry after 60 seconds."
            ),
            headers={
                "Retry-After": "60",
                "X-RateLimit-Limit": str(getattr(settings, 'RATE_LIMIT_PER_MINUTE', 60)),
                "X-RateLimit-Remaining": "0",
            }
        )

    # 6️⃣ Success
    remaining = rate_limiter.get_remaining(client_hash)
    logger.debug(
        f"Authenticated request for client {client_hash} "
        f"({request.client.host}), remaining: {remaining}"
    )
    
    # Store for later use in response headers (optional)
    request.state.rate_limit_remaining = remaining
    
    return incoming
