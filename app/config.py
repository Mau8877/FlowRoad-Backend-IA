from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = Field(default="FlowRoad AI Service", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")

    cors_origins: str = Field(
        default="http://localhost:4200,http://127.0.0.1:4200",
        alias="CORS_ORIGINS",
    )

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1/chat/completions",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_model: str = Field(
        default="openai/gpt-4o-mini",
        alias="OPENROUTER_MODEL",
    )
    openrouter_site_url: str = Field(
        default="http://localhost:4200",
        alias="OPENROUTER_SITE_URL",
    )
    openrouter_app_name: str = Field(
        default="FlowRoad",
        alias="OPENROUTER_APP_NAME",
    )

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()