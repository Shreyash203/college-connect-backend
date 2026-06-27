import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    APP_NAME: str = "College Connect"
    API_PREFIX: str = "/api"
    DATABASE_URL: Optional[str] = Field(None, env="DATABASE_URL")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(60, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    JWT_SECRET_KEY: Optional[str] = Field(None, env="JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    AUTHORIZED_EMAIL_DOMAIN: str = Field("iith.ac.in", env="AUTHORIZED_EMAIL_DOMAIN")
    AZURE_KEY_VAULT_NAME: Optional[str] = Field(None, env="AZURE_KEY_VAULT_NAME")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

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
                "AUTHORIZED_EMAIL_DOMAIN",
            ]
            for secret_name in secret_names:
                if getattr(model, secret_name) is None or secret_name not in os.environ:
                    secret = client.get_secret(secret_name)
                    secret_value = secret.value
                    if secret_name == "ACCESS_TOKEN_EXPIRE_MINUTES":
                        setattr(model, secret_name, int(secret_value))
                    else:
                        setattr(model, secret_name, secret_value)

        if model.DATABASE_URL is None:
            model.DATABASE_URL = "sqlite:///./backend.db"

        if model.JWT_SECRET_KEY is None:
            model.JWT_SECRET_KEY = "change-this-secret"

        return model


settings = Settings()
