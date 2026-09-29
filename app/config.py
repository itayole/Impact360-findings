import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


DATA_DIR = os.environ.get("DATA_DIR", os.path.join(_ROOT, "data"))
SEED_DIR = os.environ.get("SEED_DIR", os.path.join(_ROOT, "library"))
STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(_ROOT, "static"))
MAX_UPLOAD_MB = _int("MAX_UPLOAD_MB", 1024)
UPLOAD_RETENTION_DAYS = _int("UPLOAD_RETENTION_DAYS", 14)        # SAV / docx files
PROJECT_RETENTION_DAYS = _int("PROJECT_RETENTION_DAYS", 180)     # mapping + output workbook (aggregates only)
WORKERS = _int("WORKERS", 2)
CACHE_SAVS = _int("CACHE_SAVS", 3)
BUILD_TIME = os.environ.get("BUILD_TIME", "dev")
BASIC_AUTH_USER = os.environ.get("BASIC_AUTH_USER", "")          # optional; empty = no auth (internal network)
BASIC_AUTH_PASS = os.environ.get("BASIC_AUTH_PASS", "")
