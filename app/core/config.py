import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        env_file_override=True,
    )

    APP_NAME: str = "College Connect"
    API_PREFIX: str = "/api"
    ENV: str = Field("development", env="ENV")

    DATABASE_URL: Optional[str] = Field(None, env="DATABASE_URL")

    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    JWT_SECRET_KEY: Optional[str] = Field(None, env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"

    AUTHORIZED_EMAIL_DOMAINS: str = Field("iith.ac.in,gmail.com", env="AUTHORIZED_EMAIL_DOMAINS")
    GOOGLE_CLIENT_ID: str = Field("774747436427-57ign6kn9qt9tat4ipq7cnb04hio3rmn.apps.googleusercontent.com", env="GOOGLE_CLIENT_ID")

    EMAIL_PROVIDER: str = Field("acs", env="EMAIL_PROVIDER")
    EMAIL_FROM: Optional[str] = Field(None, env="EMAIL_FROM")
    ACS_EMAIL_SENDER: Optional[str] = Field(None, env="ACS_EMAIL_SENDER")
    ACS_EMAIL_CONNECTION_STRING: Optional[str] = Field(None, env="ACS_EMAIL_CONNECTION_STRING")
    ACS_EMAIL_ENDPOINT: Optional[str] = Field(None, env="ACS_EMAIL_ENDPOINT")
    ACS_EMAIL_API_KEY: Optional[str] = Field(None, env="ACS_EMAIL_API_KEY")

    APP_BASE_URL: str = Field("http://localhost:8000", env="APP_BASE_URL")
    EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES: int = Field(
        60, env="EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES"
    )
    CORS_ORIGINS: str = Field("http://localhost:4200", env="CORS_ORIGINS")

    AZURE_KEY_VAULT_NAME: Optional[str] = Field(None, env="AZURE_KEY_VAULT_NAME")
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = Field(None, env="AZURE_STORAGE_CONNECTION_STRING")
    AZURE_STORAGE_CONTAINER_NAME: Optional[str] = Field("profile-images", env="AZURE_STORAGE_CONTAINER_NAME")
    REDIS_URL: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    ADMIN_EMAILS: str = Field("shreyashbhanage@gmail.com", env="ADMIN_EMAILS")


    @property
    def authorized_email_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.AUTHORIZED_EMAIL_DOMAINS.split(",") if d.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if self.ENV.lower() in {"development", "dev", "test"}:
            for local_origin in (
                "http://localhost:4200",
                "http://127.0.0.1:4200",
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ):
                if local_origin not in origins:
                    origins.append(local_origin)
        return origins

    @model_validator(mode="after")
    def load_azure_key_vault_secrets(cls, model):
        vault_name = model.AZURE_KEY_VAULT_NAME
        if vault_name:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.keyvault.secrets import SecretClient
            except ImportError as exc:
                raise RuntimeError(
                    "Install azure-identity and azure-keyvault-secrets to load secrets from Azure Key Vault."
                ) from exc

            vault_url = f"https://{vault_name}.vault.azure.net/"
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)

            secret_mappings = [
                ("DATABASE_URL", "DATABASE-URL"),
                ("JWT_SECRET_KEY", "JWT-SECRET-KEY"),
                ("ACCESS_TOKEN_EXPIRE_MINUTES", "ACCESS-TOKEN-EXPIRE-MINUTES"),
                ("AUTHORIZED_EMAIL_DOMAINS", "AUTHORIZED-EMAIL-DOMAINS"),
                ("EMAIL_PROVIDER", "EMAIL-PROVIDER"),
                ("EMAIL_FROM", "EMAIL-FROM"),
                ("ACS_EMAIL_SENDER", "ACS-EMAIL-SENDER"),
                ("ACS_EMAIL_CONNECTION_STRING", "ACS-EMAIL-CONNECTION-STRING"),
                ("ACS_EMAIL_ENDPOINT", "ACS-EMAIL-ENDPOINT"),
                ("ACS_EMAIL_API_KEY", "ACS-EMAIL-API-KEY"),
                ("APP_BASE_URL", "APP-BASE-URL"),
                ("EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES", "EMAIL-VERIFICATION-TOKEN-EXPIRE-MINUTES"),
                ("CORS_ORIGINS", "CORS-ORIGINS"),
                ("REDIS_URL", "REDIS-URL"),
                ("AZURE_STORAGE_CONNECTION_STRING", "storage-connection-string"),
                ("AZURE_STORAGE_CONTAINER_NAME", "AZURE-STORAGE-CONTAINER-NAME"),
            ]

            for setting_name, key_vault_secret_name in secret_mappings:
                if setting_name in {"ACS_EMAIL_ENDPOINT", "ACS_EMAIL_API_KEY"} and model.ACS_EMAIL_CONNECTION_STRING:
                    continue

                if getattr(model, setting_name) is None or setting_name not in os.environ:
                    try:
                        secret = client.get_secret(key_vault_secret_name)
                        secret_value = secret.value
                        if setting_name in {
                            "ACCESS_TOKEN_EXPIRE_MINUTES",
                            "EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES",
                        }:
                            setattr(model, setting_name, int(secret_value))
                        else:
                            setattr(model, setting_name, secret_value)
                    except Exception as exc:
                        if getattr(model, setting_name) is not None:
                            continue
                        raise exc

        if model.DATABASE_URL is None:
            model.DATABASE_URL = "sqlite:///./backend.db"

        if model.JWT_SECRET_KEY is None:
            model.JWT_SECRET_KEY = "change-this-secret"

        return model


settings = Settings()