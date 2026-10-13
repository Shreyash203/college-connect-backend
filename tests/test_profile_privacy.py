import unittest

from fastapi.routing import APIRoute

from app.api import profiles
from app.core.verified_dependencies import get_current_verified_user


class ProfilePrivacyTests(unittest.TestCase):
    def test_profile_by_id_requires_verified_user(self):
        route = next(
            route
            for route in profiles.router.routes
            if isinstance(route, APIRoute) and route.path == "/profiles/{profile_id}"
        )
        dependencies = [dependency.call for dependency in route.dependant.dependencies]

        self.assertIn(get_current_verified_user, dependencies)


if __name__ == "__main__":
    unittest.main()
