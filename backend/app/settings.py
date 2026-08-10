from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения; значения переопределяются переменными окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "npz-security-flow-backend"
    app_version: str = "0.1.0"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./var/npz_security_flow.db"
    # Ограниченное ожидание блокировки SQLite: длинные retry маскируют реальную проблему записи.
    sqlite_busy_timeout_ms: int = 5000
