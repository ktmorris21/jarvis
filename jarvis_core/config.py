import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    interface_token: str = "change-me"
    heartbeat_seconds: float = 2.0
    social_trigger_seconds: float = 20.0
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    database_url: str = "sqlite:///./jarvis.db"
    stt_model: str = "gpt-4o-mini-transcribe"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    working_memory_turns: int = 16
    working_memory_timeout_seconds: int = 600
    working_memory_turn_char_limit: int = 2000
    context_memory_candidates: int = 12
    context_selected_memory_limit: int = 6
    context_goal_limit: int = 8
    context_world_state_limit: int = 12
    context_memory_accept_confidence: float = 0.80
    context_goal_accept_confidence: float = 0.90
    model_config = SettingsConfigDict(env_prefix="JARVIS_", env_file=".env", extra="ignore")

settings = Settings()
settings.openai_api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
settings.database_url = os.getenv("DATABASE_URL", settings.database_url)
