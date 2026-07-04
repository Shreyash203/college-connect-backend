import unittest

from app.api import auth


class AuthRouteTests(unittest.TestCase):
    def test_verify_email_route_is_not_registered(self):
        route_paths = {route.path for route in auth.router.routes}
        self.assertNotIn("/auth/verify-email", route_paths)
        self.assertIn("/auth/verify-registration", route_paths)


if __name__ == "__main__":
    unittest.main()
