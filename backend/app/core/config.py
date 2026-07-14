from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "UML Chatbot"
    DEBUG: bool = True

    # --- Auth ---
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # --- Database ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./uml_chatbot.db"

    # --- LLM ---
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "llama-3.3-70b-versatile"
    LLM_FALLBACK_MODELS: list[str] = [
        "llama-3.1-70b-versatile",
        "moonshotai/kimi-k2-instruct",
        "llama-3.1-8b-instant",
    ]

    # --- PlantUML ---
    # Docker-based PlantUML server URL (we run plantuml/plantuml-server container)
    PLANTUML_SERVER_URL: str = "http://localhost:8090"

    # --- Generation ---
    MAX_REPAIR_RETRIES: int = 3
    MAX_PROMPT_CHARS: int = 10000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
