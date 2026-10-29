import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException, status

from app.api.auth import check_otp_cooldown, forgot_password
from app.schemas.auth import ForgotPasswordRequest
from fastapi import BackgroundTasks


class TestOtpCooldown(unittest.IsolatedAsyncioTestCase):
    async def test_acquires_cooldown_atomically(self):
        redis_client = AsyncMock()
        redis_client.set.return_value = True

        await check_otp_cooldown(redis_client, " Student@Example.EDU ")

        redis_client.set.assert_awaited_once_with(
            "otp_cooldown:student@example.edu",
            "1",
            ex=30,
            nx=True,
        )
        redis_client.ttl.assert_not_awaited()

    async def test_rejects_request_and_returns_remaining_ttl(self):
        redis_client = AsyncMock()
        redis_client.set.return_value = None
        redis_client.ttl.return_value = 17

        with self.assertRaises(HTTPException) as error:
            await check_otp_cooldown(redis_client, "student@example.edu")

        self.assertEqual(error.exception.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(error.exception.headers["Retry-After"], "17")
        self.assertEqual(
            error.exception.detail,
            "Please wait 17 seconds before requesting another code.",
        )

    async def test_uses_minimum_retry_after_when_key_expires_during_check(self):
        redis_client = AsyncMock()
        redis_client.set.return_value = None
        redis_client.ttl.return_value = -2

        with self.assertRaises(HTTPException) as error:
            await check_otp_cooldown(redis_client, "student@example.edu")

        self.assertEqual(error.exception.headers["Retry-After"], "1")

    async def test_forgot_password_cooldown_keeps_generic_response(self):
        redis_client = AsyncMock()
        redis_client.set.return_value = None
        redis_client.ttl.return_value = 12
        db = unittest.mock.MagicMock()
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            email="student@example.edu"
        )

        response = await forgot_password(
            ForgotPasswordRequest(email="student@example.edu"),
            BackgroundTasks(),
            db,
            redis_client,
        )

        self.assertEqual(
            response,
            {
                "message": (
                    "If an account exists with this email, a password reset code "
                    "has been sent."
                )
            },
        )
        redis_client.setex.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
