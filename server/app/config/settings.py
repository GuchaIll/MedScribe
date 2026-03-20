"""
Application configuration and settings management.

Loads configuration from:
1. config.yaml (application config)
2. .env (environment variables)
3. os.environ (system environment)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional
import os
import yaml


@dataclass
class ModelConfig:
    """Model loading and inference configuration."""

    # LLM Configuration
    llm_model: Literal["api", "local"] = "api"
    llm_provider: str = "groq"  # groq, ollama, huggingface
    llm_name: str = "mixtral-8x7b-32768"
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.1
    llm_max_budget_per_run: int = 30  # Max LLM calls per workflow
    llm_timeout_seconds: int = 60

    # Speech-to-Text
    whisper_model: str = "large-v3"
    whisper_device: Literal["cpu", "cuda", "mps"] = "cpu"
    whisper_compute_type: str = "int8"
    whisper_batch_size: int = 4

    # Model Paths
    model_checkpoint_dir: Path = field(default_factory=lambda: Path("models/checkpoints"))
    soap_model_path: Optional[str] = None  # If local, path to SOAP model
    diarization_model: str = "pyannote/speaker-diarization-3.1"

    def __post_init__(self) -> None:
        """Resolve model paths and validate configuration."""
        if isinstance(self.model_checkpoint_dir, str):
            self.model_checkpoint_dir = Path(self.model_checkpoint_dir)
        self.model_checkpoint_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class DatabaseConfig:
    """Database connection and pool configuration."""

    url: str = "sqlite:///./medscribe.db"
    echo: bool = False  # SQL logging
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True  # Test connections before using
    echo_pool: bool = False


@dataclass
class StorageConfig:
    """File storage configuration."""

    backend: Literal["local", "s3", "gcs", "azure"] = "local"
    base_dir: str = "storage"
    max_file_size_mb: int = 500
    allowed_extensions: list[str] = field(default_factory=lambda: [
        "pdf", "docx", "txt", "jpg", "jpeg", "png", "tiff", "dicom", "dcm"
    ])


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file: Optional[str] = "app/logs/medscribe.log"
    log_level_file: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR"]] = "DEBUG"


@dataclass
class FeatureConfig:
    """Feature flags and feature-specific settings."""

    enable_clinical_suggestions: bool = True
    enable_human_review: bool = True
    enable_audit_logging: bool = True
    enable_performance_monitoring: bool = True
    performance_log_threshold_ms: int = 100  # Log operations slower than this


@dataclass
class Settings:
    """Complete application settings."""

    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_title: str = "MedScribe Medical Transcription API"
    api_version: str = "1.0.0"

    # Components
    model: ModelConfig = field(default_factory=ModelConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)

    # API Keys (from environment only, never in config file)
    groq_api_key: Optional[str] = None
    huggingface_token: Optional[str] = None
    eleven_labs_api_key: Optional[str] = None

    @classmethod
    def from_yaml(cls, config_path: str | Path = "config.yaml") -> "Settings":
        """Load settings from YAML config file, overridden by environment variables."""
        config_path = Path(config_path)

        if config_path.exists():
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        # Load environment-specific overrides
        settings_dict = cls._merge_with_env(data)

        # Create nested config objects
        model_config = ModelConfig(**settings_dict.get("model", {}))
        db_config = DatabaseConfig(**settings_dict.get("database", {}))
        storage_config = StorageConfig(**settings_dict.get("storage", {}))
        logging_config = LoggingConfig(**settings_dict.get("logging", {}))
        features_config = FeatureConfig(**settings_dict.get("features", {}))

        return cls(
            model=model_config,
            database=db_config,
            storage=storage_config,
            logging=logging_config,
            features=features_config,
            environment=os.getenv("ENVIRONMENT", settings_dict.get("environment", "development")),
            debug=os.getenv("DEBUG", str(settings_dict.get("debug", False))).lower() == "true",
            groq_api_key=os.getenv("GROQ_API_KEY"),
            huggingface_token=os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN"),
            eleven_labs_api_key=os.getenv("ELEVEN_LABS_API_KEY"),
        )

    @staticmethod
    def _merge_with_env(config_data: dict) -> dict:
        """Merge YAML config with environment variable overrides."""
        # Database URL override
        if db_url := os.getenv("DATABASE_URL"):
            if "database" not in config_data:
                config_data["database"] = {}
            config_data["database"]["url"] = db_url

        # Model overrides
        if llm_model := os.getenv("LLM_MODEL"):
            if "model" not in config_data:
                config_data["model"] = {}
            config_data["model"]["llm_model"] = llm_model

        return config_data

    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "production"


# Global settings instance (lazy-loaded)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings


def reset_settings() -> None:
    """Reset global settings (for testing)."""
    global _settings
    _settings = None
