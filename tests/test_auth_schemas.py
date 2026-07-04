import unittest

from app.schemas.auth import Token


class AuthSchemaTests(unittest.TestCase):
    def test_token_accepts_optional_user_id(self):
        payload = Token(access_token="abc", token_type="bearer", user_id=7)
        self.assertEqual(payload.user_id, 7)


if __name__ == "__main__":
    unittest.main()
