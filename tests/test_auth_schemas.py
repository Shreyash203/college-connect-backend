import unittest

from app.schemas.auth import EmailVerificationRequest, Token


class AuthSchemaTests(unittest.TestCase):
    def test_token_accepts_optional_user_id(self):
        payload = Token(access_token="abc", token_type="bearer", user_id=7)
        self.assertEqual(payload.user_id, 7)

    def test_email_verification_request_accepts_user_id_and_otp(self):
        payload = EmailVerificationRequest(user_id=7, otp="123456")
        self.assertEqual(payload.user_id, 7)
        self.assertEqual(payload.otp, "123456")


if __name__ == "__main__":
    unittest.main()
