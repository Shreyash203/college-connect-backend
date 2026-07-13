import time
import logging
from fastapi import Request, HTTPException, status
from app.core.redis import redis_service

logger = logging.getLogger("uvicorn.error")

class RateLimiter:
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
