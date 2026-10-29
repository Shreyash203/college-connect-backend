import unittest
import os
from unittest.mock import patch

from app.core import email_client
from app.core.config import Settings


class FakeSecret:
    def __init__(self, value):
        self.value = value


class FakeSecretClient:
    def __init__(self, *args, **kwargs):
        self.secrets = {
            "DATABASE-URL": "sqlite:///./test.db",
            "JWT-SECRET-KEY": "test-secret",
            "ACCESS-TOKEN-EXPIRE-MINUTES": "30",
            "EMAIL-PROVIDER": "acs",
            "ACS-EMAIL-SENDER": "noreply@example.com",
            "ACS-EMAIL-CONNECTION-STRING": "endpoint=https://example.com;accesskey=test",
            "APP-BASE-URL": "https://example.com",
            "EMAIL-VERIFICATION-TOKEN-EXPIRE-MINUTES": "60",
            "CORS-ORIGINS": "https://example.com",
            "REDIS-URL": "redis://localhost:6379/0",
            "storage-connection-string": "storage-connection-string",
            "AZURE-STORAGE-CONTAINER-NAME": "profiles",
        }

    def get_secret(self, name):
        from azure.core.exceptions import ResourceNotFoundError

        if name == "EMAIL-FROM":
            raise ResourceNotFoundError("Secret not found")
        return FakeSecret(self.secrets[name])


class FakeEmailClient:
    def begin_send(self, message):
        raise RuntimeError("The specified sender domain has not been linked.")


class EmailClientFallbackTests(unittest.TestCase):
    def test_normalize_acs_connection_string_lowercases_keys_and_adds_trailing_slash(self):
        connection_string = "Endpoint=https://example.communication.azure.com;AccessKey=test-key"

        normalized = email_client._normalize_acs_connection_string(connection_string)

        self.assertEqual(
            normalized,
            "endpoint=https://example.communication.azure.com/;accesskey=test-key",
        )

    def test_settings_supports_legacy_acs_fields(self):
        settings = Settings(ACS_EMAIL_ENDPOINT="https://example.communication.azure.com", ACS_EMAIL_API_KEY="test-key")
        self.assertEqual(settings.ACS_EMAIL_ENDPOINT, "https://example.communication.azure.com")
        self.assertEqual(settings.ACS_EMAIL_API_KEY, "test-key")

    def test_settings_uses_acs_sender_when_optional_email_from_secret_is_missing(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("azure.identity.DefaultAzureCredential"),
            patch("azure.keyvault.secrets.SecretClient", FakeSecretClient),
        ):
            settings = Settings(_env_file=None, AZURE_KEY_VAULT_NAME="test-vault")

        self.assertIsNone(settings.EMAIL_FROM)
        self.assertEqual(settings.ACS_EMAIL_SENDER, "noreply@example.com")

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
