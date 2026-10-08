from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL",
            "sqlite:///./data/workscheduler.db",
        )
        self.cors_origins = [
            origin.strip()
            for origin in os.getenv(
                "BACKEND_CORS_ORIGINS",
                "http://localhost:3000",
            ).split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
