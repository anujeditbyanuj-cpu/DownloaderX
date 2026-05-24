import os, re, math, asyncio, logging, yt_dlp
from config import Config

logger = logging.getLogger(__name__)


async def get_playlist_urls(url: str, range_str: str = None) -> list[str]:
    loop = asyncio.get_event_loop()
    opts = {
        "quiet": True, "no_warnings": True,
        "extract_flat": True, "skip_download": True,
    }
    if os.path.exists(Config.COOKIES_FILE):
        opts["cookiefile"] = Config.COOKIES_FILE

    start, end = 1, None
    if range_str:
        m = re.match(r"(\d+)\s*[-–]\s*(\d+)", range_str.strip())
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            opts["playliststart"] = start
            opts["playlistend"]   = end
        else:
            s = re.match(r"(\d+)", range_str.strip())
            if s:
                opts["playlistend"] = int(s.group(1))

    def _fetch():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return []
            if info.get("_type") != "playlist" and "entries" not in info:
                return [url]
            urls = []
            for e in (info.get("entries") or []):
                if not e:
                    continue
                v = e.get("url") or e.get("webpage_url") or ""
                if v and not v.startswith("http"):
                    v = f"https://www.youtube.com/watch?v={v}"
                if v:
                    urls.append(v)
            return urls

    return await loop.run_in_executor(None, _fetch)


def split_file(filepath: str, max_size: int) -> list[str]:
    size = os.path.getsize(filepath)
    if size <= max_size:
        return [filepath]
    total_parts = math.ceil(size / max_size)
    base = os.path.splitext(filepath)[0]
    ext  = os.path.splitext(filepath)[1]
    parts = []
    with open(filepath, "rb") as f:
        for n in range(1, total_parts + 1):
            chunk = f.read(max_size)
            if not chunk:
                break
            p = f"{base}.part{n:03d}{ext}"
            with open(p, "wb") as pf:
                pf.write(chunk)
            parts.append(p)
    os.remove(filepath)
    return parts


def format_size(b: int) -> str:
    if b < 1024:        return f"{b} B"
    if b < 1024**2:     return f"{b/1024:.1f} KB"
    if b < 1024**3:     return f"{b/1024**2:.1f} MB"
    return f"{b/1024**3:.2f} GB"
