from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    interface_token: str = "change-me"
    heartbeat_seconds: float = 2.0
    social_trigger_seconds: float = 20.0

    model_config = SettingsConfigDict(
        env_prefix="JARVIS_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
