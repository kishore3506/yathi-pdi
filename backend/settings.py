import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    return path.resolve()


def load_environment() -> None:
    configured_path = os.getenv("PDI_ENV_FILE")
    if configured_path:
        env_path = _resolve_path(configured_path)
        if not env_path.is_file():
            raise FileNotFoundError(f"PDI_ENV_FILE does not exist: {env_path}")
        env_paths = (env_path,)
    else:
        env_paths = (BACKEND_DIR / ".env", APP_DIR / ".env")

    for env_path in env_paths:
        try:
            with env_path.open(encoding="utf-8") as env_file:
                for raw_line in env_file:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    key, separator, value = line.partition("=")
                    if separator:
                        os.environ.setdefault(
                            key.strip(), value.strip().strip('"').strip("'")
                        )
                return
        except FileNotFoundError:
            continue


load_environment()

DATA_DIR = _resolve_path(os.getenv("PDI_DATA_DIR", str(BACKEND_DIR)))
DATABASE_PATH = _resolve_path(
    os.getenv("PDI_DATABASE_PATH", str(DATA_DIR / "pdi_system.db"))
)
UPLOAD_DIR = _resolve_path(os.getenv("PDI_UPLOAD_DIR", str(DATA_DIR / "uploads")))
REPORTS_DIR = _resolve_path(
    os.getenv("PDI_REPORTS_DIR", str(DATA_DIR / "generated_reports"))
)
CUSTOM_TEMPLATES_DIR = _resolve_path(
    os.getenv("PDI_TEMPLATE_STORAGE_DIR", str(DATA_DIR / "user_templates"))
)
LOG_DIR = _resolve_path(os.getenv("PDI_LOG_DIR", str(DATA_DIR / "logs")))
BACKUP_DIR = _resolve_path(os.getenv("PDI_BACKUP_DIR", str(DATA_DIR / "backups")))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", str(8 * 60 * 60)))
LOG_MAX_BYTES = int(os.getenv("PDI_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("PDI_LOG_BACKUP_COUNT", "10"))


def ensure_data_directories():
    for path in (
        DATA_DIR,
        UPLOAD_DIR,
        REPORTS_DIR,
        CUSTOM_TEMPLATES_DIR,
        LOG_DIR,
        BACKUP_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
