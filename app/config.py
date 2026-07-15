from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlparse


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

    # JWT
    jwt_secret_key: str = "changeme-very-secret-katha-2026"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 8

    # Cloudinary
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_url: str = ""

    # Transbank Webpay Plus
    transbank_commerce_code: str = "597055555532"  # Código de integración por defecto
    transbank_api_key: str = "579B532A7440BB0116B0A3D54BF3B38E"  # Clave de integración
    transbank_environment: str = "integration"  # "integration" | "production"

    # URL pública del frontend (para redirigir tras el pago)
    frontend_url: str = "https://arteyartesaniakatha.cl"

    @property
    def cors_origins_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def postgres_dsn(self) -> str:
        db_url = (self.database_url or "").strip()
        if db_url:
            # Compatibilidad: algunos providers entregan postgres:// en vez de postgresql://
            normalized = db_url.replace("postgres://", "postgresql://", 1)
            scheme = urlparse(normalized).scheme
            if scheme in {"postgresql", "postgres"}:
                return normalized

        ssl_mode = "require" if self.postgres_ssl else "disable"
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}?sslmode={ssl_mode}"
        )


settings = Settings()
