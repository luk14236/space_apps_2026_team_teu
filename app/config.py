"""App settings (environment variables). AI-assisted: written with Claude (Anthropic) and reviewed by the team."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=value per line). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")  # local secrets (gitignored); see .env.example
DATA_DIR = Path(os.environ.get("FOCOS_DATA_DIR", ROOT / "data"))
RAW_DIR = Path(os.environ.get("FOCOS_RAW_DIR", DATA_DIR / "raw"))              # deliveries (CSV)
PROCESSED_DIR = Path(os.environ.get("FOCOS_PROCESSED_DIR", DATA_DIR / "processed"))  # what the app reads
GEO_DIR = Path(os.environ.get("FOCOS_GEO_DIR", DATA_DIR / "geo"))              # boundaries (versioned)

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8050"))
DEBUG = os.environ.get("DASH_DEBUG", "0") == "1"

# /admin: login required. Without ADMIN_USER and ADMIN_PASSWORD the admin is disabled.
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()  # set it in production so logins survive restarts
FIRMS_MAP_KEY = os.environ.get("FIRMS_MAP_KEY", "")
