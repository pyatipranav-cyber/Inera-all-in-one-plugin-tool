"""InEra All-in-One Plugins - configuration.

Every setting comes from environment variables. A `.env` file placed next to
this file is loaded automatically (simple KEY=VALUE lines, no quotes needed).
Nothing here is secret by default; secrets are generated on first run and kept
inside the data directory with owner-only permissions.
"""
import os
import secrets
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
APP_NAME = "InEra All-in-One Plugins"
APP_VERSION = "1.0.0"


def _load_dotenv() -> None:
    env_file = APP_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------- storage
DATA_DIR = Path(env_str("INERA_DATA_DIR") or (Path.home() / "inera_data")).expanduser().resolve()
FILES_DIR = DATA_DIR / "files"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "inera.db"
for _d in (DATA_DIR, FILES_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- server
HOST = env_str("INERA_HOST", "0.0.0.0")
PORT = env_int("INERA_PORT", 8000)
PUBLIC_BASE_URL = env_str("PUBLIC_BASE_URL").rstrip("/")
COOKIE_SECURE = env_bool("COOKIE_SECURE", PUBLIC_BASE_URL.startswith("https://"))
TRUST_PROXY = env_bool("TRUST_PROXY", False)
# Addresses of your reverse proxy whose X-Forwarded-For header is trusted (comma-separated).
FORWARDED_ALLOW_IPS = env_str("FORWARDED_ALLOW_IPS", "127.0.0.1")
ALLOW_REGISTRATION = env_bool("ALLOW_REGISTRATION", True)
ADMIN_EMAILS = {e.strip().lower() for e in env_str("ADMIN_EMAILS").split(",") if e.strip()}
SESSION_DAYS = env_int("SESSION_DAYS", 14)

# ---------------------------------------------------------------- limits
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 50)
MAX_FILES_PER_RUN = env_int("MAX_FILES_PER_RUN", 20)
WORKERS = max(1, env_int("WORKERS", 2))
MAX_CONCURRENT_JOBS_PER_USER = max(1, env_int("MAX_CONCURRENT_JOBS_PER_USER", 2))
MAX_RUNS_PER_DAY = env_int("MAX_RUNS_PER_DAY", 200)
MAX_AUTOMATIONS_PER_USER = env_int("MAX_AUTOMATIONS_PER_USER", 25)
MIN_INTERVAL_MINUTES = max(5, env_int("MIN_INTERVAL_MINUTES", 15))
RETENTION_DAYS = env_int("RETENTION_DAYS", 30)
ALLOW_PRIVATE_NETWORK = env_bool("ALLOW_PRIVATE_NETWORK", False)

# ---------------------------------------------------------------- AI engine
LLM_PROVIDER = env_str("LLM_PROVIDER", "auto").lower()  # auto|ollama|openai|anthropic|none
OLLAMA_URL = env_str("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = env_str("OLLAMA_MODEL", "llama3.1")
OPENAI_API_KEY = env_str("OPENAI_API_KEY")
OPENAI_BASE_URL = env_str("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = env_str("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = env_str("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = env_str("ANTHROPIC_MODEL", "claude-sonnet-5-5")
LLM_TIMEOUT = env_int("LLM_TIMEOUT", 180)

# ---------------------------------------------------------------- research & media
WEB_RESEARCH = env_bool("WEB_RESEARCH", True)
WIKI_LANG = env_str("WIKI_LANG", "en")
CONTACT_EMAIL = env_str("CONTACT_EMAIL", "admin@example.com")
USER_AGENT = f"InEraAllInOne/{APP_VERSION} (+{PUBLIC_BASE_URL or 'self-hosted'}; {CONTACT_EMAIL})"
PIPER_MODEL = env_str("PIPER_MODEL")
TTS_VOICE = env_str("TTS_VOICE", "en-us")
VIDEO_WIDTH = env_int("VIDEO_WIDTH", 1280)
VIDEO_HEIGHT = env_int("VIDEO_HEIGHT", 720)
OCR_LANGS = env_str("OCR_LANGS", "eng")

# ---------------------------------------------------------------- integrations
IG_GRAPH_HOST = env_str("IG_GRAPH_HOST", "graph.instagram.com")
IG_GRAPH_VERSION = env_str("IG_GRAPH_VERSION", "v25.0")


def _load_or_create_secret() -> str:
    explicit = env_str("SECRET_KEY")
    if explicit:
        return explicit
    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    key_file.write_text(value, encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return value


SECRET_KEY = _load_or_create_secret()
