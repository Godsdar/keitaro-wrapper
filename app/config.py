from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения или файла .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Keitaro: адрес трекера без /admin и ключ из «Профиль → API ключи».
    keitaro_url: str = "https://tlgk.host"
    keitaro_api_key: str = ""
    keitaro_timeout: float = 30.0

    # Все кампании создаются с этим префиксом (по условию тестового).
    campaign_prefix: str = "test_familiya_"

    # Значения по умолчанию для создаватора — подставляются в форму,
    # их можно поменять там же. Ищутся по имени среди того, что отдаёт API.
    default_domain: str = "in.posdk.xyz"
    default_group: str = "FORTESTS"
    default_source: str = "FORTESTS"

    # Куда первый поток отправляет трафик из выбранной страны.
    geo_redirect_url: str = "https://www.google.com"

    database_url: str = "sqlite:///./keitaro_wrapper.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
