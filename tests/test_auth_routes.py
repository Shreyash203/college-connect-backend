import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api import auth
from app.core.dependencies import decode_access_token, get_current_user


class AuthRouteTests(unittest.TestCase):
    def test_verify_email_route_is_not_registered(self):
        route_paths = {route.path for route in auth.router.routes}
        self.assertNotIn("/auth/verify-email", route_paths)
        self.assertIn("/auth/verify-registration", route_paths)

    def test_access_token_contains_user_claims_without_database_lookup(self):
        user = SimpleNamespace(
            id=7,
            email="student@example.edu",
            college_domain="example.edu",
            is_verified=True,
            is_admin=False,
        )

        token = auth.create_user_access_token(user)

        self.assertEqual(
            decode_access_token(token),
            get_current_user(token),
        )
        self.assertEqual(get_current_user(token).id, user.id)
        self.assertEqual(get_current_user(token).email, user.email)
        self.assertEqual(get_current_user(token).college_domain, user.college_domain)
        self.assertTrue(get_current_user(token).is_verified)
        self.assertFalse(get_current_user(token).is_admin)

    def test_access_token_without_required_claims_is_rejected(self):
        token = auth.security.create_refresh_token(subject="7")

        with self.assertRaises(HTTPException) as error:
            decode_access_token(token)

        self.assertEqual(error.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
