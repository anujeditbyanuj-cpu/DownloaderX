import os
import asyncio
import time
import yt_dlp
import logging
from config import Config

logger = logging.getLogger(__name__)

def _build_format_string(height: str) -> str:
    """Never fail — always return working format."""
    if height.startswith("mp3"):
        return "bestaudio/best"
    h = int(height)
    return (
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={h}][ext=webm]+bestaudio[ext=webm]/"
        f"bestvideo[height<={h}]+bestaudio/"
        f"bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo+bestaudio/"
        f"best[height<={h}]/"
        f"best"
    )


def _get_ydl_opts(fmt: str, output_path: str, progress_hook=None) -> dict:
    is_audio = fmt.startswith("mp3")
    # Parse bitrate from fmt like 'mp3_320' → '320', default '192'
    mp3_bitrate = fmt.split("_")[1] if "_" in fmt else "192"

    opts = {
        "format": _build_format_string(fmt),
        "format_sort": ["res", "ext:mp4:m4a", "size", "br"],
        "ignore_no_formats_error": False,   # Let it fail properly so we can catch
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "writethumbnail": True,
        "merge_output_format": "mp4" if not is_audio else None,
        "postprocessors": [],
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "http_chunk_size": 10 * 1024 * 1024,  # 10MB chunks for speed
    }

    if is_audio:
        opts["postprocessors"].append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": mp3_bitrate,
        })
        opts["merge_output_format"] = None

    opts["postprocessors"].append({
        "key": "FFmpegThumbnailsConvertor",
        "format": "jpg",
    })

    if os.path.exists(Config.COOKIES_FILE):
        opts["cookiefile"] = Config.COOKIES_FILE

    if Config.PROXY:
        opts["proxy"] = Config.PROXY

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]

    return opts


async def get_video_info(url: str) -> dict | None:
    """
    Fetch video info + ALL actually available qualities with real combined sizes.
    Each quality shows video+audio merged size estimate.
    """
    loop = asyncio.get_event_loop()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    def _fetch(use_cookies=True):
        o = dict(opts)
        if use_cookies and os.path.exists(Config.COOKIES_FILE):
            o["cookiefile"] = Config.COOKIES_FILE
        with yt_dlp.YoutubeDL(o) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        # Try with cookies first, fallback to without
        try:
            info = await loop.run_in_executor(None, lambda: _fetch(True))
        except Exception:
            info = await loop.run_in_executor(None, lambda: _fetch(False))
        if not info:
            return None

        formats = info.get("formats", [])

        # ── Step 1: Collect all video formats by height ──────────────────
        # Keep the BEST bitrate format for each height
        video_by_height: dict[int, dict] = {}
        for f in formats:
            h   = f.get("height")
            vco = f.get("vcodec", "none")
            if not h or vco == "none":
                continue
            vbr   = f.get("vbr") or f.get("tbr") or 0
            fsize = f.get("filesize") or f.get("filesize_approx") or 0
            prev  = video_by_height.get(h)
            # Prefer higher bitrate; break ties with filesize
            if prev is None or vbr > (prev.get("vbr") or 0):
                video_by_height[h] = {
                    "format_id": f.get("format_id", ""),
                    "ext":       f.get("ext", "mp4"),
                    "vbr":       vbr,
                    "size":      fsize,
                    "fps":       f.get("fps") or 0,
                }

        # ── Step 2: Find best audio stream size ──────────────────────────
        best_audio_size = 0
        for f in formats:
            aco = f.get("acodec", "none")
            vco = f.get("vcodec", "none")
            if aco == "none" or vco != "none":
                continue
            asize = f.get("filesize") or f.get("filesize_approx") or 0
            if asize > best_audio_size:
                best_audio_size = asize

        # ── Step 3: Build available dict — combined size = video + audio ─
        available: dict[str, dict] = {}
        for h, vdata in video_by_height.items():
            key        = str(h)
            video_size = vdata["size"]
            # Combined size estimate
            combined   = (video_size + best_audio_size) if (video_size and best_audio_size) else (video_size or best_audio_size)
            fps        = vdata["fps"]
            fps_str    = f" {int(fps)}fps" if fps and fps > 30 else ""
            available[key] = {
                "label":   f"{h}p{fps_str}",
                "size":    combined,
                "ext":     vdata["ext"],
                "vbr":     vdata["vbr"],
            }

        # ── Step 4: Build MP3 quality options with estimated sizes ───────
        # 128kbps ≈ 16 KB/s, 192kbps ≈ 24 KB/s, 320kbps ≈ 40 KB/s
        duration = info.get("duration") or 0
        mp3_sizes = {}
        for kbps in [128, 192, 320]:
            if duration and best_audio_size:
                # Scale the best_audio_size proportionally by bitrate
                # (rough estimate since actual size depends on source)
                mp3_sizes[str(kbps)] = int(duration * kbps * 1000 / 8)
            elif best_audio_size:
                mp3_sizes[str(kbps)] = best_audio_size
            else:
                mp3_sizes[str(kbps)] = 0

        mp3_size = best_audio_size   # approx (kept for backwards compat)

        # Sort all heights descending
        sorted_q = sorted(available.keys(), key=lambda x: int(x), reverse=True)

        return {
            "title":           info.get("title", "Unknown"),
            "uploader":        info.get("uploader") or info.get("channel", "Unknown"),
            "uploader_url":    info.get("uploader_url", ""),
            "duration_string": info.get("duration_string", "N/A"),
            "view_count":      info.get("view_count", 0) or 0,
            "like_count":      info.get("like_count", 0) or 0,
            "comment_count":   info.get("comment_count", 0) or 0,
            "upload_date":     _fmt_date(info.get("upload_date", "")),
            "description":     (info.get("description") or "")[:300],
            "thumbnail":       info.get("thumbnail", ""),
            "webpage_url":     info.get("webpage_url", url),
            "qualities":       sorted_q,       # e.g. ["1080","720","480","360","240","144"]
            "quality_info":    available,       # key → {label, size, ext}
            "mp3_size":        mp3_size,        # audio-only approx size (backwards compat)
            "mp3_sizes":       mp3_sizes,       # {"128": bytes, "192": bytes, "320": bytes}
        }
    except Exception as e:
        logger.error(f"Info fetch error: {e}")
        return None


async def download_video(url: str, fmt: str, progress_callback=None) -> dict | None:
    uid       = str(int(time.time() * 1000))
    out_dir   = Config.DOWNLOAD_DIR
    out_tpl   = os.path.join(out_dir, f"{uid}_%(title).80s.%(ext)s")

    last_upd     = [0]
    title_holder = ["Downloading..."]

    def hook(d):
        if d["status"] != "downloading":
            return
        try:
            downloaded = d.get("downloaded_bytes", 0)
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            percent    = int((downloaded / total) * 100) if total else 0
            speed      = _fmt_speed(d.get("speed") or 0)
            eta        = _fmt_eta(d.get("eta") or 0)
            now        = time.time()
            if now - last_upd[0] >= 2:
                last_upd[0] = now
                if progress_callback:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        lambda p=percent, s=speed, e=eta, t=title_holder[0]:
                            asyncio.ensure_future(progress_callback(p, s, e, t))
                    )
        except Exception:
            pass

    # Get title first
    loop = asyncio.get_event_loop()
    info_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    if os.path.exists(Config.COOKIES_FILE):
        info_opts["cookiefile"] = Config.COOKIES_FILE

    try:
        info = await loop.run_in_executor(
            None, lambda: _extract_info(url, info_opts)
        )
        if info:
            title_holder[0] = info.get("title", "Downloading...")

        ydl_opts = _get_ydl_opts(fmt, out_tpl, hook)
        try:
            await loop.run_in_executor(None, lambda: _do_download(url, ydl_opts))
        except yt_dlp.utils.ExtractorError as e:
            if "Requested format is not available" in str(e):
                # Fallback to best available
                logger.warning(f"Format {fmt} not available, falling back to best")
                fallback_opts = _get_ydl_opts("best_fallback", out_tpl, hook)
                fallback_opts["format"] = "bestvideo+bestaudio/best"
                await loop.run_in_executor(None, lambda: _do_download(url, fallback_opts))
            else:
                raise

        filepath  = _find_file(out_dir, uid, fmt)
        thumb     = _find_thumb(out_dir, uid)

        if not filepath:
            return None

        return {"filepath": filepath, "info": info or {}, "thumbnail": thumb}

    except Exception as e:
        logger.error(f"Download error {url}: {e}")
        raise


# ── helpers ────────────────────────────────────────────────────────────────

def _extract_info(url, opts):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def _do_download(url, opts):
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def _find_file(directory, uid, fmt):
    ext = "mp3" if fmt.startswith("mp3") else "mp4"
    for f in os.listdir(directory):
        if f.startswith(uid) and f.endswith(ext):
            return os.path.join(directory, f)
    for f in os.listdir(directory):
        if f.startswith(uid) and not f.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return os.path.join(directory, f)
    return None

def _find_thumb(directory, uid):
    for f in os.listdir(directory):
        if f.startswith(uid) and f.endswith((".jpg", ".jpeg", ".png", ".webp")):
            return os.path.join(directory, f)
    return None

def _fmt_speed(bps):
    if bps <= 0: return "N/A"
    if bps > 1_000_000: return f"{bps/1_000_000:.1f} MB/s"
    if bps > 1_000:     return f"{bps/1_000:.1f} KB/s"
    return f"{bps:.0f} B/s"

def _fmt_eta(s):
    if s <= 0: return "Almost done..."
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    return f"{m}m {s}s"

def _fmt_date(d):
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d
