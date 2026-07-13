import redis.asyncio as aioredis
from app.core.config import settings

class RedisService:
    def __init__(self):
        self.client: aioredis.Redis | None = None

    def get_client(self) -> aioredis.Redis:
        if self.client is None:
            # decode_responses=True parses standard Redis bytes into Python strings automatically
            self.client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self.client

    async def close(self):
        if self.client:
            await self.client.close()
            self.client = None

redis_service = RedisService()

async def get_redis() -> aioredis.Redis:
    return redis_service.get_client()
