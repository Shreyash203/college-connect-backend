import unittest

from app.core import email_verification


class VerificationOtpTests(unittest.TestCase):
    def test_generate_otp_code_returns_six_digits(self):
        otp = email_verification.generate_otp_code()
        self.assertRegex(otp, r"^\d{6}$")


if __name__ == "__main__":
    unittest.main()
