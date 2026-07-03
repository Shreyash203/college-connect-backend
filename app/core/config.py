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

    @property
    def authorized_email_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.AUTHORIZED_EMAIL_DOMAINS.split(",") if d.strip()]

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

            secret_names = [
                "DATABASE_URL",
                "JWT_SECRET_KEY",
                "ACCESS_TOKEN_EXPIRE_MINUTES",
                "AUTHORIZED_EMAIL_DOMAINS",
                "EMAIL_PROVIDER",
                "EMAIL_FROM",
                "ACS_EMAIL_SENDER",
                "ACS_EMAIL_CONNECTION_STRING",
                "ACS_EMAIL_ENDPOINT",
                "ACS_EMAIL_API_KEY",
                "APP_BASE_URL",
                "EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES",
                "CORS_ORIGINS",
            ]

            for secret_name in secret_names:
                if getattr(model, secret_name) is None or secret_name not in os.environ:
                    secret = client.get_secret(secret_name)
                    secret_value = secret.value
                    if secret_name in {
                        "ACCESS_TOKEN_EXPIRE_MINUTES",
                        "EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES",
                    }:
                        setattr(model, secret_name, int(secret_value))
                    else:
                        setattr(model, secret_name, secret_value)

        if model.DATABASE_URL is None:
            model.DATABASE_URL = "sqlite:///./backend.db"

        if model.JWT_SECRET_KEY is None:
            model.JWT_SECRET_KEY = "change-this-secret"

        return model


settings = Settings()