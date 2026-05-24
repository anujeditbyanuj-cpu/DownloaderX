import asyncio
import yt_dlp
import logging
from config import Config

logger = logging.getLogger(__name__)


async def youtube_search(query: str, max_results: int = 20) -> list[dict]:
    """
    Search YouTube and return up to max_results video info dicts.
    No filtering — returns exactly what YouTube returns.
    Each dict: id, title, uploader, duration_string, view_count, url, thumbnail
    """
    loop = asyncio.get_event_loop()

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "default_search": f"ytsearch{max_results}",
    }
    if Config.COOKIES_FILE:
        import os
        if os.path.exists(Config.COOKIES_FILE):
            opts["cookiefile"] = Config.COOKIES_FILE

    def _search():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            if not info or "entries" not in info:
                return []
            results = []
            for e in info["entries"]:
                if not e:
                    continue
                vid_id = e.get("id", "")
                results.append({
                    "id":              vid_id,
                    "title":           e.get("title", "Unknown")[:60],
                    "uploader":        e.get("uploader") or e.get("channel", "Unknown"),
                    "duration_string": e.get("duration_string") or _fmt_dur(e.get("duration", 0)),
                    "view_count":      e.get("view_count", 0) or 0,
                    "url":             f"https://www.youtube.com/watch?v={vid_id}",
                    "thumbnail":       e.get("thumbnail", ""),
                })
            return results

    try:
        return await loop.run_in_executor(None, _search)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []


def _fmt_dur(secs):
    if not secs:
        return "N/A"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
