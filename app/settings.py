from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    GOOGLE_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./helix.db"
    CHROMA_PATH: str = "./.chroma"
    LLM_TIMEOUT_SECONDS: int = 30
    MODEL_NAME: str = "gemini-2.5-flash"
    GROQ_MODEL_NAME: str = "groq/llama-3.3-70b-versatile"
    EMBED_MODEL: str = "models/gemini-embedding-2"
    USE_LOCAL_EMBEDDINGS: bool = True


settings = Settings()
