from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ENV: str = "development"
    APP_NAME: str = "college-connect-backend"

    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # DB (MySQL)
    MYSQL_HOST: str
    MYSQL_PORT: int = 3306
    MYSQL_DB: str
    MYSQL_USER: str
    MYSQL_PASSWORD: str

    # CORS - comma separated, e.g. "https://site1.com,https://site2.com"
    CORS_ORIGINS: str = "http://localhost:4200"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}"
        )


settings = Settings()