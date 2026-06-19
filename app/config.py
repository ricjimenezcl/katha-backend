from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_port: int = 8000
    app_name: str = "Katha Backend API"
    cors_origins: str = "http://localhost:4200"
    nominatim_user_agent: str = "KathaEcommerce/1.0 (contacto@katha.cl)"

    # Render suele inyectar DATABASE_URL para PostgreSQL administrado.
    database_url: str | None = None

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "dbkatha"
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_ssl: bool = False

    render_external_url: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def postgres_dsn(self) -> str:
        if self.database_url:
            # Compatibilidad: algunos providers entregan postgres:// en vez de postgresql://
            return self.database_url.replace("postgres://", "postgresql://", 1)

        ssl_mode = "require" if self.postgres_ssl else "disable"
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?sslmode={ssl_mode}"
        )


settings = Settings()
