from typing import Dict, Optional

from azure.communication.email import EmailClient
from azure.core.credentials import AzureKeyCredential

from app.core.config import settings


def _normalize_acs_connection_string(connection_string: str) -> str:
    normalized_parts: list[str] = []

    for raw_part in connection_string.split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue

        key, value = part.split("=", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()

        if normalized_key == "endpoint" and normalized_value and not normalized_value.endswith("/"):
            normalized_value = f"{normalized_value}/"

        normalized_parts.append(f"{normalized_key}={normalized_value}")

    return ";".join(normalized_parts)


class EmailService:
    def __init__(self):
        self.client = None
        self.dev_fallback = settings.ENV.lower() in {"development", "dev", "test"}
        self._initialize()

    def _initialize(self):
        if settings.EMAIL_PROVIDER != "acs":
            if settings.ENV.lower() in {"development", "dev", "test"}:
                return
            raise RuntimeError("Only ACS email provider is implemented currently.")

        connection_string = getattr(settings, "ACS_EMAIL_CONNECTION_STRING", None)
        if connection_string:
            self.client = EmailClient.from_connection_string(
                _normalize_acs_connection_string(connection_string)
            )
            return

        endpoint = getattr(settings, "ACS_EMAIL_ENDPOINT", None)
        api_key = getattr(settings, "ACS_EMAIL_API_KEY", None)
        if not endpoint or not api_key:
            if settings.ENV.lower() in {"development", "dev", "test"}:
                return
            raise RuntimeError("Azure Communication Services endpoint and API key must be configured.")

        credential = AzureKeyCredential(api_key)
        self.client = EmailClient(
            endpoint=endpoint,
            credential=credential,
        )

    def send_email(self, to_address: str, subject: str, html_body: str, plain_body: str) -> Dict[str, Optional[str]]:
        if not self.client:
            if settings.ENV.lower() in {"development", "dev", "test"}:
                return {
                    "status": "dev-fallback",
                    "message": "Email delivery skipped in development mode because ACS is not configured properly.",
                }
            raise RuntimeError("Azure Communication Services client is not initialized.")

        sender_address = (
            getattr(settings, "EMAIL_FROM", None)
            or getattr(settings, "ACS_EMAIL_SENDER", None)
            or getattr(settings, "ACS_EMAIL_FROM", None)
        )
        if not sender_address or sender_address.startswith("your-sender"):
            if settings.ENV.lower() in {"development", "dev", "test"}:
                return {
                    "status": "dev-fallback",
                    "message": "Email delivery skipped because the sender address is not configured with a real ACS sender.",
                }
            raise RuntimeError("A verified ACS sender address must be configured in EMAIL_FROM or ACS_EMAIL_SENDER.")

        print("Sending OTP email to:", to_address)
        print("Using configured sender:", sender_address)

        message = {
            "senderAddress": sender_address,
            "content": {
                "subject": subject,
                "html": html_body,
                "plainText": plain_body,
            },
            "recipients": {
                "to": [
                    {
                        "address": to_address,
                    }
                ]
            },
        }

        try:
            poller = self.client.begin_send(message)
            print("Email send started")
            response = poller.result()
            return response
        except Exception as exc:
            if settings.ENV.lower() in {"development", "dev", "test"}:
                return {
                    "status": "dev-fallback",
                    "message": f"Email delivery skipped in development mode due to ACS error: {exc}",
                }
            raise RuntimeError(f"Failed to send email via Azure Communication Services: {exc}") from exc
