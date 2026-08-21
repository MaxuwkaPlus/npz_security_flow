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

    # Срок жизни токена доступа. Истёкший токен требует повторного входа;
    # отзыв действует сразу, потому что состояние сеанса хранится на сервере.
    auth_token_ttl_minutes: int = 720

    # Самостоятельное прохождение: пульт открывается без входа, а токен выдаётся
    # гостевой учётной записи. Кабинет эксперта и рабочее место администратора ИБ
    # этот режим не затрагивает — туда по-прежнему только по учётной записи.
    # В контуре, где обучение должно быть именным, выключается одной переменной.
    allow_guest_training: bool = True
    # Гостевой токен живёт заметно меньше именного: учётная запись за ним ничья,
    # и оставлять её действующей на сутки незачем.
    guest_token_ttl_minutes: int = 240

    # Во сколько раз симуляционное время идёт быстрее реального.
    # 1.0 — режим эксплуатации, большие значения нужны для демонстрации и нагрузочных прогонов.
    simulation_speed_factor: float = 1.0
