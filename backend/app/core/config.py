from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    frontend_origin: str = "http://127.0.0.1:5173"
    cookie_secure: bool = False
    access_token_minutes: int = 60
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    google_sheets_spreadsheet_id: str | None = None
    google_sheets_range: str = "Form Responses 1!A:Z"
    google_service_account_json: str | None = None
    google_sheets_api_key: str | None = None
    email_mode: str = "development"
    brevo_api_key: str | None = None
    email_from: str | None = None
    email_from_name: str = "Department of Artificial Intelligence & Data Science"
    email_reply_to: str | None = None

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
