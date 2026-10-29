import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
from fastapi.routing import APIRoute
from unittest.mock import patch

from app.api import profiles
from app.api.profiles import (
    MAX_PROFILE_IMAGE_SIZE,
    enforce_profile_blob_size,
    get_owned_profile_blob_name,
)
from app.core.dependencies import AuthenticatedUser
from app.core.rate_limiter import DailyUploadRateLimiter


class FakeBlobProperties:
    def __init__(self, size: int):
        self.size = size


class FakeBlobClient:
    def __init__(self, size: int):
        self.size = size
        self.deleted = False

    def get_blob_properties(self):
        return FakeBlobProperties(self.size)

    def delete_blob(self):
        self.deleted = True


class ProfileUploadLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_profile_upload_url_route_has_daily_rate_limit(self):
        route = next(
            route
            for route in profiles.router.routes
            if isinstance(route, APIRoute) and route.path == "/profiles/me/upload-url"
        )
        self.assertTrue(
            any(
                isinstance(dependency.call, DailyUploadRateLimiter)
                for dependency in route.dependant.dependencies
            )
        )

    async def test_daily_upload_limit_is_scoped_to_user_and_endpoint(self):
        limiter = DailyUploadRateLimiter(limit=3)
        redis_client = SimpleNamespace(
            get=AsyncMock(return_value=None),
            incr=AsyncMock(),
            expire=AsyncMock(),
        )
        request = SimpleNamespace(
            url=SimpleNamespace(path="/profiles/me/upload-url"),
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        users = [
            AuthenticatedUser(1, "one@example.com", "example.com", True, False),
            AuthenticatedUser(2, "two@example.com", "example.com", True, False),
        ]

        with patch("app.core.rate_limiter.redis_service.get_client", return_value=redis_client):
            for user in users:
                await limiter(request, user)

        keys = [call.args[0] for call in redis_client.get.call_args_list]
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])
        self.assertIn(":1:/profiles/me/upload-url:", keys[0])
        self.assertIn(":2:/profiles/me/upload-url:", keys[1])

    def test_accepts_image_at_10_mib_limit(self):
        blob = FakeBlobClient(MAX_PROFILE_IMAGE_SIZE)

        enforce_profile_blob_size(blob)

        self.assertFalse(blob.deleted)

    def test_deletes_image_over_10_mib_limit(self):
        blob = FakeBlobClient(MAX_PROFILE_IMAGE_SIZE + 1)

        with self.assertRaises(HTTPException) as context:
            enforce_profile_blob_size(blob)

        self.assertEqual(context.exception.status_code, 413)
        self.assertTrue(blob.deleted)

    def test_profile_blob_name_must_be_owned_by_current_user(self):
        blob_name = "profile_images/user_7/12345678-1234-1234-1234-123456789abc.jpg"
        image_url = f"https://testaccount.blob.core.windows.net/images/{blob_name}?sig=token"

        with patch(
            "app.api.profiles.verify_azure_host_and_container",
            return_value=("images", blob_name),
        ):
            self.assertEqual(get_owned_profile_blob_name(image_url, 7), blob_name)
            with self.assertRaises(HTTPException):
                get_owned_profile_blob_name(image_url, 8)


if __name__ == "__main__":
    unittest.main()
