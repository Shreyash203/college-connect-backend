import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from app.core.rate_limiter import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.request = MagicMock()
        self.request.client.host = "127.0.0.1"
        self.request.headers.get.return_value = None
        self.request.url.path = "/test-endpoint"

    @staticmethod
    def make_pipeline(execute_result=None, execute_error=None):
        pipeline = MagicMock()
        pipeline.__aenter__ = AsyncMock(return_value=pipeline)
        pipeline.__aexit__ = AsyncMock(return_value=None)
        if execute_error:
            pipeline.execute = AsyncMock(side_effect=execute_error)
        else:
            pipeline.execute = AsyncMock(return_value=execute_result)
        return pipeline

    async def test_allows_requests_below_limit(self):
        read_pipeline = self.make_pipeline((None, 2))
        write_pipeline = self.make_pipeline((None, None))
        mock_client = MagicMock()
        mock_client.pipeline.side_effect = [read_pipeline, write_pipeline]

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            await SlidingWindowRateLimiter(limit=5, window_seconds=60)(self.request)

        read_pipeline.zremrangebyscore.assert_called_once()
        read_pipeline.zcard.assert_called_once()
        write_pipeline.zadd.assert_called_once()
        write_pipeline.expire.assert_called_once()

    async def test_blocks_requests_at_limit(self):
        read_pipeline = self.make_pipeline((None, 5))
        mock_client = MagicMock()
        mock_client.pipeline.return_value = read_pipeline

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            with self.assertRaises(HTTPException) as context:
                await SlidingWindowRateLimiter(limit=5, window_seconds=60)(self.request)

        self.assertEqual(context.exception.status_code, 429)
        mock_client.pipeline.assert_called_once_with(transaction=True)
        read_pipeline.zadd.assert_not_called()

    async def test_fails_open_on_redis_error(self):
        read_pipeline = self.make_pipeline(execute_error=ConnectionError("Redis Down"))
        mock_client = MagicMock()
        mock_client.pipeline.return_value = read_pipeline

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=mock_client):
            await SlidingWindowRateLimiter(limit=5, window_seconds=60)(self.request)


if __name__ == "__main__":
    unittest.main()
