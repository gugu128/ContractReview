from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


_BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(str(_BASE_DIR / ".env"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_reasoning_model: str = "deepseek-chat"
    deepseek_fast_model: str = "deepseek-chat"
    doubao_model: str = "doubao-1.5-pro"
    request_timeout: float = 60.0
    max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
