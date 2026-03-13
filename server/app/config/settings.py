"""
Configuration management using Pydantic Settings.
Environment-based configuration for development and production.
"""

from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Environment
    ENVIRONMENT: str = "development"  # development, staging, production
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/medscribe"
    DB_ECHO: bool = False  # SQLAlchemy echo mode
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # Redis (for session management - post-MVP)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None

    # Storage
    STORAGE_BACKEND: str = "local"  # local, s3, gcp, azure
    STORAGE_BASE_DIR: str = "storage"

    # AWS S3 (for production - post-MVP)
    S3_BUCKET: Optional[str] = None
    S3_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # Security & Authentication
    SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION"  # Used for JWT signing
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Encryption (for PHI data)
    ENCRYPTION_KEY: Optional[str] = None  # Fernet key for field-level encryption

    # External APIs
    GROQ_API_KEY: Optional[str] = None
    HUGGINGFACE_API_KEY: Optional[str] = None
    HF_TOKEN: Optional[str] = None

    # LLM Configuration
    LLM_MODEL: str = "api"  # "local" or "api"
    LLM_MAX_BUDGET: int = 30  # Max LLM calls per workflow
    LLM_MAX_TOKENS: int = 2000
    LLM_TEMPERATURE: float = 0.1

    # Whisper Configuration
    WHISPER_MODEL: str = "large-v3"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"

    # Feature Flags
    ENABLE_CLINICAL_SUGGESTIONS: bool = True
    ENABLE_HUMAN_REVIEW: bool = True
    ENABLE_AUDIT_LOGGING: bool = True

    # Application Settings
    APP_NAME: str = "Medical Transcription API"
    APP_VERSION: str = "1.0.0-mvp"
    API_PREFIX: str = "/api"

    # CORS (comma-separated string, will be parsed to list)
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: str = "*"
    CORS_HEADERS: str = "*"

    # Logging
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Workflow Settings
    CHECKPOINT_DB_PATH: str = "storage/checkpoints.db"
    MAX_WORKFLOW_RETRIES: int = 3
    WORKFLOW_TIMEOUT_SECONDS: int = 300  # 5 minutes

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Dependency injection function for FastAPI."""
    return settings


def get_database_url() -> str:
    """Get database URL, fallback to environment variable."""
    return settings.DATABASE_URL or os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/medscribe"
    )


def is_production() -> bool:
    """Check if running in production environment."""
    return settings.ENVIRONMENT.lower() == "production"


def is_development() -> bool:
    """Check if running in development environment."""
    return settings.ENVIRONMENT.lower() == "development"


def get_cors_origins() -> list[str]:
    """Parse CORS origins from comma-separated string to list."""
    if not settings.CORS_ORIGINS:
        return []
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]


# Storage factory function
def get_storage_backend():
    """Get storage backend based on configuration."""
    from app.storage.local import LocalStorage

    if settings.STORAGE_BACKEND == "local":
        return LocalStorage(base_dir=settings.STORAGE_BASE_DIR)
    elif settings.STORAGE_BACKEND == "s3":
        # Post-MVP: Import and return S3Storage
        from app.storage.s3 import S3Storage
        return S3Storage(
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION
        )
    else:
        # Default to local storage
        return LocalStorage(base_dir=settings.STORAGE_BASE_DIR)
