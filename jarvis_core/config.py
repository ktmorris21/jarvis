import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    interface_token: str = "change-me"
    heartbeat_seconds: float = 2.0
    agent_model: str = "gpt-5.6-luna"
    agent_max_turns: int = 4
    agent_timeout_seconds: float = 50.0
    agent_status_timeout_seconds: float = 6.0
    autonomous_curiosity_enabled: bool = False
    curiosity_trigger: float = 0.75
    curiosity_increment: float = 0.01
    curiosity_cooldown_seconds: float = 45.0
    social_trigger_seconds: float = 20.0
    openai_api_key: str | None = None
    vision_model: str = "gpt-5.6-luna"
    database_url: str = "sqlite:///./jarvis.db"
    stt_model: str = "gpt-transcribe"
    tts_provider: str = "piper"
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str = "Q8ZbQAANLFvLw8uPBR8d"
    elevenlabs_model: str = "eleven_flash_v2_5"
    humor_level: int = 75
    sarcasm_level: int = 65
    tts_instructions: str = (
        "Speak in a calm, refined British English accent, with crisp articulation "
        "and measured pacing. Sound composed, intelligent, quietly warm, and "
        "occasionally dryly witty. Avoid exaggerated theatricality, excessive "
        "enthusiasm, or a cartoonish robot effect. Be natural and conversational."
    )
    context_goal_limit: int = 8
    model_config = SettingsConfigDict(env_prefix="JARVIS_", env_file=".env", extra="ignore")

settings = Settings()
settings.openai_api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
settings.database_url = os.getenv("DATABASE_URL", settings.database_url)

settings.elevenlabs_api_key = settings.elevenlabs_api_key or os.getenv("ELEVENLABS_API_KEY")
