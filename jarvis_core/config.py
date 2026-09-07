import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    interface_token: str = "change-me"
    heartbeat_seconds: float = 2.0
    social_trigger_seconds: float = 20.0
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    database_url: str = "sqlite:///./jarvis.db"
    model_config = SettingsConfigDict(env_prefix="JARVIS_", env_file=".env", extra="ignore")

settings = Settings()
settings.openai_api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
settings.database_url = os.getenv("DATABASE_URL", settings.database_url)
