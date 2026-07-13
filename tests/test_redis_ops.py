import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from app.core.rate_limiter import RateLimiter

class TestRateLimiter(unittest.TestCase):
    def test_rate_limiter_allows_requests_below_limit(self):
        # Mock request
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.url.path = "/test-endpoint"

        # Mock Redis client with pipelines
        mock_client = MagicMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = (None, 2)  # Return 2 requests (below limit of 5)
        mock_client.pipeline.return_value.__aenter__.return_value = mock_pipe

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            limiter = RateLimiter(limit=5, window_seconds=60)
            
            async def run():
                await limiter(request)
                
            asyncio.run(run())

            mock_pipe.zremrangebyscore.assert_called_once()
            mock_pipe.zcard.assert_called_once()
            mock_pipe.zadd.assert_called_once()
            mock_pipe.expire.assert_called_once()

    def test_rate_limiter_blocks_requests_above_limit(self):
        # Mock request
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.url.path = "/test-endpoint"

        # Mock Redis client
        mock_client = MagicMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute.return_value = (None, 5)  # Return 5 requests (equal to limit of 5)
        mock_client.pipeline.return_value.__aenter__.return_value = mock_pipe

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            limiter = RateLimiter(limit=5, window_seconds=60)
            
            async def run():
                with self.assertRaises(HTTPException) as context:
                    await limiter(request)
                self.assertEqual(context.exception.status_code, 429)

            asyncio.run(run())

    def test_rate_limiter_fails_open_on_redis_error(self):
        # Mock request
        request = MagicMock()
        request.client.host = "127.0.0.1"
        request.url.path = "/test-endpoint"

        # Mock Redis client causing connection error
        mock_client = MagicMock()
        mock_client.pipeline.side_effect = Exception("Redis Down")

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            limiter = RateLimiter(limit=5, window_seconds=60)
            
            async def run():
                try:
                    await limiter(request)
                except Exception as e:
                    self.fail(f"Rate Limiter failed to fail-open: raised {e}")

            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
