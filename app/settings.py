from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GOOGLE_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./helix.db"
    CHROMA_PATH: str = "./.chroma"
    LLM_TIMEOUT_SECONDS: int = 30
    MODEL_NAME: str = "gemini-2.0-flash"
    EMBED_MODEL: str = "models/text-embedding-004"


settings = Settings()
