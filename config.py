from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INTERNAL_EVENTS_API_URL = (
    "http://student-system-events-provider-web"
    ".student-system-events-provider.svc:8000"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    events_api_key: str = ""
    events_api_url: str = INTERNAL_EVENTS_API_URL
    postgres_connection_string: str = ""
    postgres_host: str = "localhost"
    postgres_port: str = "5432"
    postgres_database_name: str = "events"
    postgres_username: str = "postgres"
    postgres_password: str = "postgres"

    @property
    def provider_base_url(self) -> str:
        url = self.events_api_url.strip().rstrip("/")
        if url.startswith("http://") and ".svc" in url:
            return url
        return INTERNAL_EVENTS_API_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
