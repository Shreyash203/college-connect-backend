import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.chat import ConnectionManager, redis_listener


class TestConnectionManager(unittest.IsolatedAsyncioTestCase):
    async def test_connections_share_one_redis_listener(self):
        manager = ConnectionManager()
        listener_started = asyncio.Event()

        async def wait_for_cancellation():
            listener_started.set()
            await asyncio.Event().wait()

        websocket_one = AsyncMock()
        websocket_two = AsyncMock()
        with patch(
            "app.api.chat.redis_listener",
            side_effect=wait_for_cancellation,
        ) as listener:
            await manager.connect(1, websocket_one)
            await listener_started.wait()
            await manager.connect(2, websocket_two)

            self.assertEqual(listener.call_count, 1)
            self.assertEqual(len(manager.active_connections), 2)

            task = manager.redis_listener_task
            manager.disconnect(1, websocket_one)
            self.assertIs(manager.redis_listener_task, task)
            self.assertFalse(task.cancelled())

            manager.disconnect(2, websocket_two)
            self.assertIsNone(manager.redis_listener_task)
            await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(task.cancelled())

    async def test_pattern_listener_routes_message_to_channel_user(self):
        pubsub = AsyncMock()

        async def listen():
            yield {
                "type": "pmessage",
                "channel": "chat:42",
                "data": '{"content":"hello"}',
            }
            yield {
                "type": "pmessage",
                "channel": "chat:not-a-user",
                "data": "{}",
            }

        pubsub.listen = listen
        redis = MagicMock()
        redis.pubsub.return_value = pubsub
        with (
            patch("app.api.chat.get_redis", new=AsyncMock(return_value=redis)),
            patch(
                "app.api.chat.manager.send_personal_message",
                new=AsyncMock(),
            ) as send_personal_message,
        ):
            await redis_listener()

        pubsub.psubscribe.assert_awaited_once_with("chat:*")
        send_personal_message.assert_awaited_once_with(
            '{"content":"hello"}',
            42,
        )
        pubsub.punsubscribe.assert_awaited_once_with("chat:*")
        pubsub.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
