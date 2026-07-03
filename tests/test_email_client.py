import unittest
from unittest.mock import patch

from app.core import email_client
from app.core.config import Settings


class FakeEmailClient:
    def begin_send(self, message):
        raise RuntimeError("The specified sender domain has not been linked.")


class EmailClientFallbackTests(unittest.TestCase):
    def test_settings_supports_legacy_acs_fields(self):
        settings = Settings(ACS_EMAIL_ENDPOINT="https://example.communication.azure.com", ACS_EMAIL_API_KEY="test-key")
        self.assertEqual(settings.ACS_EMAIL_ENDPOINT, "https://example.communication.azure.com")
        self.assertEqual(settings.ACS_EMAIL_API_KEY, "test-key")

    def test_send_email_falls_back_in_development_when_azure_rejects_sender(self):
        service = email_client.EmailService.__new__(email_client.EmailService)
        service.client = FakeEmailClient()

        with patch.object(email_client.settings, "ENV", "development"), patch.object(email_client.settings, "EMAIL_PROVIDER", "acs"), patch.object(email_client.settings, "EMAIL_FROM", "your-sender@yourdomain.com"):
            result = service.send_email(
                to_address="student@example.com",
                subject="Verify your email",
                html_body="<p>Hello</p>",
                plain_body="Hello",
            )

        self.assertEqual(result["status"], "dev-fallback")
        self.assertIn("sender", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
