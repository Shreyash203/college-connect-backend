import time
import logging
from datetime import datetime, timedelta
from fastapi import Request, HTTPException, status
from app.core.redis import redis_service

logger = logging.getLogger("uvicorn.error")

class SlidingWindowRateLimiter:
    """
    A sliding window rate limiter implemented via Redis Sorted Sets (ZSET).
    Can be used as a FastAPI dependency.
    """
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        endpoint = request.url.path
        key = f"rate_limit:{client_ip}:{endpoint}"

        client = redis_service.get_client()
        now = time.time()
        clear_before = now - self.window_seconds

        try:
            # Execute zremrangebyscore and zcard inside a Redis pipeline transaction
            async with client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, clear_before)
                pipe.zcard(key)
                _, current_requests = await pipe.execute()

            if current_requests >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many requests. Please try again later."
                )

            # Record the current request with unique score and value (both = timestamp)
            async with client.pipeline(transaction=True) as pipe:
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, self.window_seconds)
                await pipe.execute()

        except HTTPException:
            raise
        except Exception as exc:
            # Fail-open design: Log the error, but allow the request if Redis is down
            logger.error(f"Rate Limiter Redis connection failed: {exc}. Access allowed.")


class DailyUploadRateLimiter:
    """
    A daily upload rate limiter that restricts uploads to 3 per day per IP.
    Uses a Redis key with date suffix to track daily uploads.
    """
    def __init__(self, limit: int = 3):
        self.limit = limit

    async def __call__(self, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        endpoint = request.url.path
        
        # Only limit upload endpoints
        if "upload-url" not in endpoint:
            return
            
        today = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"daily_upload_limit:{client_ip}:{today}"

        client = redis_service.get_client()
        
        try:
            current_count = await client.get(key)
            current_count = int(current_count) if current_count else 0
            
            if current_count >= self.limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Daily upload limit exceeded. Maximum 3 uploads per day."
                )
            
            # Increment the counter with 24-hour TTL
            await client.incr(key)
            await client.expire(key, 86400)  # 24 hours

        except HTTPException:
            raise
        except Exception as exc:
            # Fail-open design: Log the error, but allow the request if Redis is down
            logger.error(f"Daily Upload Limiter Redis connection failed: {exc}. Access allowed.")
