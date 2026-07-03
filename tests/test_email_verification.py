import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.core import email_verification


class VerificationOtpTests(unittest.TestCase):
    def test_generate_otp_code_returns_six_digits(self):
        otp = email_verification.generate_otp_code()
        self.assertRegex(otp, r"^\d{6}$")

    def test_is_verification_otp_valid_checks_expiry(self):
        user = SimpleNamespace(
            verification_otp="123456",
            verification_otp_expires_at=datetime.utcnow() - timedelta(minutes=1),
        )
        self.assertFalse(email_verification.is_verification_otp_valid(user, "123456"))


if __name__ == "__main__":
    unittest.main()
