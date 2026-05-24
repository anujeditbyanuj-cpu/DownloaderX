import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── Telegram ──────────────────────────────────────────────
    API_ID    = int(os.getenv("API_ID", "34446649"))
    API_HASH  = os.getenv("API_HASH", "8dc570c08d8e35e88fb9bfc73c65d7fa")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8840114975:AAFucalzGzQso1AoDAS_0qXdIBAjd7z0QE4")

    # ── YouTube Cookies ───────────────────────────────────────
    # cookies.txt file repo mein alag rakho (Netscape format)
    COOKIES_FILE = os.getenv("COOKIES_FILE", "downloads/cookies.txt")

    # ── Download Settings ─────────────────────────────────────
    DOWNLOAD_DIR     = os.getenv("DOWNLOAD_DIR", "downloads")
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "2000"))   # 2 GB
    CHUNK_SIZE_MB    = int(os.getenv("CHUNK_SIZE_MB", "1900"))      # 1.9 GB chunks

    # ── Concurrency ───────────────────────────────────────────
    MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))

    # ── Proxy (optional) ──────────────────────────────────────
    PROXY = os.getenv("PROXY", "None")

    # ── Web Server (Render health check) ─────────────────────
    PORT = int(os.getenv("PORT", "5000"))


# Class ke bahar — sirf ek baar run hoga
os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
