"""
YouTube Playlist Downloader Bot
Features:
  • YouTube Search (/search query)
  • Inline quality selection buttons (1080p / 720p / 480p / 360p / 144p + MP3 128/192/320kbps)
  • Full video info + thumbnail before download
  • 2 GB Telegram upload support (streaming)
  • Auto file split for >2GB
  • Playlist/channel with range
  • Cookies support (age-restrict bypass)
  • Live progress bar
  • /cancel support
  • Flask health check for Render deployment
"""

import os, asyncio, logging, time, threading
from flask import Flask, jsonify
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from config import Config
from downloader import download_video, get_video_info
from search import youtube_search
from utils import get_playlist_urls, split_file, format_size

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Client(
    "yt_dl_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

# ── Flask web server (Render needs an HTTP port to stay alive) ────────────────
web = Flask(__name__)
_start_time = time.time()

@web.route("/")
def index():
    return jsonify({
        "status": "ok",
        "bot":    "YouTube Downloader Bot",
        "uptime": f"{int(time.time() - _start_time)}s",
    })

@web.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@web.route("/stats")
def stats():
    return jsonify({
        "active_downloads": len(active_downloads),
        "pending_urls":     len(pending_url),
        "uptime_seconds":   int(time.time() - _start_time),
    })

def _run_web():
    web.run(host="0.0.0.0", port=Config.PORT, use_reloader=False)
# ─────────────────────────────────────────────────────────────────────────────



def _clean_url(url: str) -> str:
    """Remove tracking parameters like &si= from YouTube URLs."""
    import re
    url = re.sub(r'[&?]si=[^&]*', '', url)
    url = re.sub(r'\n.*', '', url)  # Remove anything after newline
    url = url.strip().rstrip('?&')
    return url

# ── State stores ──────────────────────────────────────────────────────────────
active_downloads: dict[int, dict] = {}   # uid → {cancel: bool}
pending_url:      dict[int, str]  = {}   # uid → url waiting for quality pick
search_results:   dict[int, list] = {}   # uid → list of search result dicts
# ─────────────────────────────────────────────────────────────────────────────


# ════════════════════════════════════════════════════════════════════════════
#  /start
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(filters.command("start"))
async def cmd_start(_, msg: Message):
    await msg.reply_text(
        "👋 **YouTube Downloader Bot**\n\n"
        "🔗 Send a YouTube link — OR — use `/search` to find videos\n\n"
        "**Commands:**\n"
        "`/search <query>` — Search YouTube (20 results)\n"
        "`/channel @handle 1-20` — Download channel range\n"
        "`/cancel` — Stop active download\n"
        "`/setformat [mp3_128|mp3_192|mp3_320|360|480|720|1080]` — Default format\n\n"
        "**🎵 Music Quality:**\n"
        "`mp3_128` — 128 kbps (small size)\n"
        "`mp3_192` — 192 kbps (balanced)\n"
        "`mp3_320` — 320 kbps (best quality)\n\n"
        "**Playlist range:**\n"
        "`https://youtube.com/playlist?list=xxx | 1-10`\n\n"
        "📦 Max upload: **2 GB** (auto-split if larger)",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


# ════════════════════════════════════════════════════════════════════════════
#  /cancel
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(filters.command("cancel"))
async def cmd_cancel(_, msg: Message):
    uid = msg.from_user.id
    if uid in active_downloads:
        active_downloads[uid]["cancel"] = True
        await msg.reply_text("🛑 **Download cancelled!**", parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await msg.reply_text("❌ No active download.")


# ════════════════════════════════════════════════════════════════════════════
#  /setformat
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(filters.command("setformat"))
async def cmd_setformat(_, msg: Message):
    valid = ["mp3_128", "mp3_192", "mp3_320", "144", "240", "360", "480", "720", "1080"]
    args  = msg.command
    if len(args) < 2 or args[1] not in valid:
        await msg.reply_text(
            f"Usage: `/setformat [{' | '.join(valid)}]`",
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return
    if not hasattr(app, "user_fmt"):
        app.user_fmt = {}
    app.user_fmt[msg.from_user.id] = args[1]
    await msg.reply_text(f"✅ Default format → **{args[1]}**", parse_mode=enums.ParseMode.MARKDOWN)


# ════════════════════════════════════════════════════════════════════════════
#  /search
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(filters.command("search"))
async def cmd_search(_, msg: Message):
    args = msg.text.split(None, 1)
    if len(args) < 2:
        await msg.reply_text("Usage: `/search <song name>`", parse_mode=enums.ParseMode.MARKDOWN)
        return

    query   = args[1].strip()
    uid     = msg.from_user.id
    wait_m  = await msg.reply_text(f"🔍 Searching: **{query}**...", parse_mode=enums.ParseMode.MARKDOWN)

    results = await youtube_search(query, max_results=20)
    if not results:
        await wait_m.edit_text("❌ No results found.")
        return

    search_results[uid] = results

    # Build numbered list + inline buttons
    text = "🎵 **Search Results:**\n\n"
    buttons = []
    row = []
    for i, r in enumerate(results, 1):
        views = f"{r['view_count']:,}" if r['view_count'] else "N/A"
        text += (
            f"**{i}.** {r['title']}\n"
            f"   👤 {r['uploader']}  ⏱ {r['duration_string']}  👁 {views}\n\n"
        )
        row.append(InlineKeyboardButton(str(i), callback_data=f"search_pick:{uid}:{i-1}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"search_cancel:{uid}")])

    await wait_m.edit_text(
        text,
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ════════════════════════════════════════════════════════════════════════════
#  Callback: search pick
# ════════════════════════════════════════════════════════════════════════════
@app.on_callback_query(filters.regex(r"^search_pick:"))
async def cb_search_pick(_, cq: CallbackQuery):
    _, uid_str, idx_str = cq.data.split(":")
    uid = int(uid_str)
    idx = int(idx_str)

    if cq.from_user.id != uid:
        await cq.answer("Not your search!", show_alert=True)
        return

    results = search_results.get(uid)
    if not results or idx >= len(results):
        await cq.answer("Expired. Search again.", show_alert=True)
        return

    chosen = results[idx]
    await cq.message.edit_text(
        f"✅ Selected: **{chosen['title']}**\nFetching formats...",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await cq.answer()
    await _show_quality_menu(cq.message, uid, chosen["url"])


@app.on_callback_query(filters.regex(r"^search_cancel:"))
async def cb_search_cancel(_, cq: CallbackQuery):
    uid = int(cq.data.split(":")[1])
    if cq.from_user.id != uid:
        await cq.answer()
        return
    search_results.pop(uid, None)
    await cq.message.edit_text("❌ Search cancelled.")
    await cq.answer()


# ════════════════════════════════════════════════════════════════════════════
#  /channel
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(filters.command("channel"))
async def cmd_channel(_, msg: Message):
    args = msg.text.split(None, 2)
    if len(args) < 2:
        await msg.reply_text("Usage: `/channel @handle [1-20]`", parse_mode=enums.ParseMode.MARKDOWN)
        return
    handle    = args[1]
    range_str = args[2] if len(args) > 2 else None
    url       = f"https://www.youtube.com/{handle}/videos"
    await _process_playlist(msg, url, range_str)


# ════════════════════════════════════════════════════════════════════════════
#  Plain text handler — YouTube link or playlist
# ════════════════════════════════════════════════════════════════════════════
@app.on_message(
    filters.text
    & ~filters.command(["start","cancel","setformat","search","channel"])
)
async def handle_text(_, msg: Message):
    text = msg.text.strip()

    range_str = None
    if "|" in text:
        url, range_str = [p.strip() for p in text.split("|", 1)]
    else:
        url = text
    url = _clean_url(url)

    if "youtube.com" not in url and "youtu.be" not in url:
        await msg.reply_text("❌ Send a valid YouTube link or use `/search`.", parse_mode=enums.ParseMode.MARKDOWN)
        return

    # Playlist / channel
    if "playlist?list=" in url or "/channel/" in url or "/@" in url:
        await _process_playlist(msg, url, range_str)
        return

    # Single video → show quality menu
    wait_m = await msg.reply_text("🔍 Fetching video info...", parse_mode=enums.ParseMode.MARKDOWN)
    await _show_quality_menu(wait_m, msg.from_user.id, url)


# ════════════════════════════════════════════════════════════════════════════
#  Quality menu helper
# ════════════════════════════════════════════════════════════════════════════
async def _show_quality_menu(status_msg: Message, uid: int, url: str):
    info = await get_video_info(url)
    if not info:
        await status_msg.edit_text("❌ Could not fetch video info. Try again.")
        return

    pending_url[uid] = url

    title    = info["title"]
    uploader = info["uploader"]
    dur      = info["duration_string"]
    views    = f"{info['view_count']:,}"
    likes    = f"{info['like_count']:,}"
    date     = info["upload_date"]
    q_info   = info["quality_info"]

    # ── Build quality buttons — 2 per row ────────────────────────────────
    # Each button shows real detected quality + combined file size
    q_buttons = []
    row = []

    for q in info["qualities"]:   # already sorted high→low
        label    = q_info[q]["label"]          # e.g. "1080p" or "1080p 60fps"
        size     = q_info[q]["size"]
        size_str = f" · {format_size(size)}" if size else ""
        btn_txt  = f"🎬 {label}{size_str}"
        row.append(InlineKeyboardButton(btn_txt, callback_data=f"dl:{uid}:{q}"))
        if len(row) == 2:
            q_buttons.append(row)
            row = []
    if row:
        q_buttons.append(row)

    # MP3 audio quality buttons (3 options in one row)
    mp3_sizes = info.get("mp3_sizes", {})
    mp3_row = []
    for kbps in ["128", "192", "320"]:
        sz = mp3_sizes.get(kbps, 0)
        sz_str = f" · {format_size(sz)}" if sz else ""
        mp3_row.append(
            InlineKeyboardButton(
                f"🎵 MP3 {kbps}k{sz_str}",
                callback_data=f"dl:{uid}:mp3_{kbps}",
            )
        )
    q_buttons.append(mp3_row)

    # Thumbnail + Description
    q_buttons.append([
        InlineKeyboardButton("🖼 Thumbnail", callback_data=f"thumb:{uid}"),
        InlineKeyboardButton("📝 Description", callback_data=f"desc:{uid}"),
    ])

    q_buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"dl_cancel:{uid}")])

    # Info text listing all qualities (like the screenshot)
    quality_lines = ""
    for q in info["qualities"]:
        lbl  = q_info[q]["label"]
        sz   = q_info[q]["size"]
        sz_s = format_size(sz) if sz else "N/A"
        quality_lines += f"✅  {lbl} - {sz_s}\n"
    mp3_sizes = info.get("mp3_sizes", {})
    for kbps in ["128", "192", "320"]:
        sz = mp3_sizes.get(kbps, 0)
        sz_s = format_size(sz) if sz else "N/A"
        quality_lines += f"✅  MP3 {kbps}kbps - {sz_s}\n"

    caption = (
        f"🎬 **{title}**\n\n"
        f"👤 {uploader}\n"
        f"⏱ {dur}  |  👁 {views}  |  👍 {likes}\n"
        f"📅 {date}\n\n"
        f"📦 **Formats for download:**\n"
        f"{quality_lines}\n"
        f"⬇️ **Choose quality below:**"
    )

    # Send thumbnail + caption + buttons
    thumb_url = info.get("thumbnail")
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Store info for thumb/desc callbacks
    if not hasattr(app, "vid_info_cache"):
        app.vid_info_cache = {}
    app.vid_info_cache[uid] = info

    if thumb_url:
        await app.send_photo(
            status_msg.chat.id,
            photo=thumb_url,
            caption=caption,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(q_buttons),
        )
    else:
        await app.send_message(
            status_msg.chat.id,
            caption,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(q_buttons),
        )


# ════════════════════════════════════════════════════════════════════════════
#  Callback: quality selected → download
# ════════════════════════════════════════════════════════════════════════════
@app.on_callback_query(filters.regex(r"^dl:"))
async def cb_download(_, cq: CallbackQuery):
    parts = cq.data.split(":", 2)   # maxsplit=2 so fmt like "mp3_320" stays intact
    uid   = int(parts[1])
    fmt   = parts[2]

    if cq.from_user.id != uid:
        await cq.answer("Not your request!", show_alert=True)
        return

    url = pending_url.get(uid)
    if not url:
        await cq.answer("Session expired. Send link again.", show_alert=True)
        return

    await cq.answer(f"⬇️ Starting {fmt} download...")

    # Edit message to show starting state
    try:
        await cq.message.edit_caption(
            cq.message.caption + f"\n\n⏳ **Preparing {fmt} download...**",
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=None,
        )
    except Exception:
        pass

    await _run_single_download(
        chat_id=cq.message.chat.id,
        uid=uid,
        url=url,
        fmt=fmt,
        status_msg=cq.message,
        idx=1,
        total=1,
    )
    pending_url.pop(uid, None)


@app.on_callback_query(filters.regex(r"^dl_cancel:"))
async def cb_dl_cancel(_, cq: CallbackQuery):
    uid = int(cq.data.split(":")[1])
    if cq.from_user.id != uid:
        await cq.answer()
        return
    pending_url.pop(uid, None)
    try:
        await cq.message.edit_caption("❌ Cancelled.", reply_markup=None)
    except Exception:
        await cq.message.delete()
    await cq.answer()


# ════════════════════════════════════════════════════════════════════════════
#  Callback: thumbnail & description
# ════════════════════════════════════════════════════════════════════════════
@app.on_callback_query(filters.regex(r"^thumb:"))
async def cb_thumb(_, cq: CallbackQuery):
    uid  = int(cq.data.split(":")[1])
    if cq.from_user.id != uid:
        await cq.answer()
        return
    info = getattr(app, "vid_info_cache", {}).get(uid)
    if not info or not info.get("thumbnail"):
        await cq.answer("No thumbnail available.", show_alert=True)
        return
    await cq.answer()
    await app.send_photo(
        cq.message.chat.id,
        photo=info["thumbnail"],
        caption=f"🖼 **{info['title']}**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@app.on_callback_query(filters.regex(r"^desc:"))
async def cb_desc(_, cq: CallbackQuery):
    uid  = int(cq.data.split(":")[1])
    if cq.from_user.id != uid:
        await cq.answer()
        return
    info = getattr(app, "vid_info_cache", {}).get(uid)
    if not info:
        await cq.answer("Info not found.", show_alert=True)
        return
    await cq.answer()
    desc = info.get("description") or "No description."
    await app.send_message(
        cq.message.chat.id,
        f"📝 **Description:**\n\n{desc}",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


# ════════════════════════════════════════════════════════════════════════════
#  Single download runner (reused by both single & playlist)
# ════════════════════════════════════════════════════════════════════════════
async def _run_single_download(
    chat_id: int,
    uid: int,
    url: str,
    fmt: str,
    status_msg: Message,
    idx: int,
    total: int,
):
    active_downloads[uid] = {"cancel": False}

    try:
        async def prog(percent, speed, eta, title):
            if active_downloads.get(uid, {}).get("cancel"):
                return
            bar   = "⬢" * int(percent / 10) + "⬡" * (10 - int(percent / 10))
            label = f"📥 **Downloading {idx}/{total}**\n🎬 `{title[:38]}`\n\n"
            box   = (
                "┌─────《 Progress 》─────┐\n"
                f"├» [{bar}] {percent}%\n"
                f"├» 🚀 Speed: {speed}\n"
                f"├» ⏱ ETA: {eta}\n"
                "└──────────────────────┘"
            )
            try:
                await status_msg.edit_caption(label + box, parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                pass

        result = await download_video(url, fmt, prog)
        if not result:
            await app.send_message(chat_id, f"❌ Download failed for video {idx}.")
            return

        filepath = result["filepath"]
        info     = result["info"]
        thumb    = result.get("thumbnail")

        fsize    = os.path.getsize(filepath)
        MAX_TG   = Config.MAX_FILE_SIZE_MB * 1024 * 1024   # default 2 GB

        caption = _build_caption(info, fmt, fsize, idx, total)

        if fsize > MAX_TG:
            # Split
            try:
                await status_msg.edit_caption(
                    f"✂️ **Splitting {format_size(fsize)} file into chunks...**",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            parts       = split_file(filepath, MAX_TG)
            total_parts = len(parts)
            for pi, part in enumerate(parts, 1):
                if active_downloads.get(uid, {}).get("cancel"):
                    break
                try:
                    await status_msg.edit_caption(
                        f"📤 Uploading part **{pi}/{total_parts}**...",
                        parse_mode=enums.ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass
                part_cap = caption + f"\n📂 Part **{pi}/{total_parts}**"
                await _send_file(chat_id, part, fmt, part_cap, thumb if pi == 1 else None, info)
                os.remove(part)
        else:
            try:
                await status_msg.edit_caption("📤 **Uploading...**", parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                pass
            await _send_file(chat_id, filepath, fmt, caption, thumb, info)
            if os.path.exists(filepath):
                os.remove(filepath)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    except Exception as e:
        logger.error(f"_run_single_download error: {e}")
        await app.send_message(chat_id, f"❌ Error: `{str(e)[:200]}`", parse_mode=enums.ParseMode.MARKDOWN)
    finally:
        active_downloads.pop(uid, None)


async def _send_file(chat_id, filepath, fmt, caption, thumb, info):
    """Send file to Telegram chat (video/audio/document)."""
    fsize = os.path.getsize(filepath)
    try:
        if fmt.startswith("mp3"):
            await app.send_audio(
                chat_id,
                audio=filepath,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                title=info.get("title", ""),
                performer=info.get("uploader", ""),
                thumb=thumb,
            )
        else:
            await app.send_video(
                chat_id,
                video=filepath,
                caption=caption,
                parse_mode=enums.ParseMode.MARKDOWN,
                thumb=thumb,
                supports_streaming=True,
            )
    except Exception as e:
        # Fallback: send as document
        logger.warning(f"send_video/audio failed ({e}), falling back to document")
        await app.send_document(
            chat_id,
            document=filepath,
            caption=caption,
            parse_mode=enums.ParseMode.MARKDOWN,
            thumb=thumb,
        )


def _build_caption(info, fmt, fsize, idx, total):
    title    = info.get("title", "Unknown")
    uploader = info.get("uploader", "Unknown")
    dur      = info.get("duration_string", "N/A")
    views    = f"{info.get('view_count', 0) or 0:,}"
    likes    = f"{info.get('like_count', 0) or 0:,}"
    date     = info.get("upload_date", "N/A")
    fmt_label = fmt.replace("mp3_", "MP3 ").upper() if fmt.startswith("mp3_") else fmt.upper()
    return (
        f"🎬 **{title}**\n"
        f"👤 {uploader}\n"
        f"⏱ {dur}  👁 {views}  👍 {likes}\n"
        f"📅 {date}\n"
        f"📁 **{fmt_label}**  📦 {format_size(fsize)}\n"
        + (f"🔢 Video **{idx}/{total}**" if total > 1 else "")
    )


# ════════════════════════════════════════════════════════════════════════════
#  Playlist processor
# ════════════════════════════════════════════════════════════════════════════
async def _process_playlist(msg: Message, url: str, range_str: str = None):
    uid      = msg.from_user.id
    fmt      = getattr(app, "user_fmt", {}).get(uid, "480")

    if uid in active_downloads:
        await msg.reply_text("⚠️ Already downloading! Use /cancel to stop.")
        return

    status = await msg.reply_text("🔍 **Fetching playlist...**", parse_mode=enums.ParseMode.MARKDOWN)

    try:
        urls = await get_playlist_urls(url, range_str)
    except Exception as e:
        await status.edit_text(f"❌ Error: `{e}`", parse_mode=enums.ParseMode.MARKDOWN)
        return

    if not urls:
        await status.edit_text("❌ No videos found. Check the URL/range.")
        return

    total   = len(urls)
    ok, fail = 0, 0

    await status.edit_text(
        f"📋 **{total} video(s) found**\n"
        f"📁 Format: **{fmt}**\n⏳ Starting...",
        parse_mode=enums.ParseMode.MARKDOWN,
    )

    active_downloads[uid] = {"cancel": False}

    for i, vurl in enumerate(urls, 1):
        if active_downloads.get(uid, {}).get("cancel"):
            break
        try:
            await status.edit_text(
                f"⬇️ **{i}/{total}** Preparing...",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            await _run_single_download(
                chat_id=msg.chat.id,
                uid=uid,
                url=vurl,
                fmt=fmt,
                status_msg=status,
                idx=i,
                total=total,
            )
            ok += 1
            # re-create status after _run_single_download pops uid
            active_downloads[uid] = {"cancel": False}
        except Exception as e:
            fail += 1
            logger.error(f"Playlist item {i} error: {e}")
            await msg.reply_text(f"❌ Video {i} failed: `{str(e)[:100]}`", parse_mode=enums.ParseMode.MARKDOWN)

    was_cancelled = active_downloads.get(uid, {}).get("cancel", False)
    active_downloads.pop(uid, None)
    icon = "🛑" if was_cancelled else "✅"
    await status.edit_text(
        f"{icon} **Done!**\n✔️ Success: **{ok}/{total}**\n❌ Failed: **{fail}/{total}**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )


# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logger.info("🌐 Starting Flask health server on port %s...", Config.PORT)
    t = threading.Thread(target=_run_web, daemon=True)
    t.start()
    logger.info("🤖 Bot starting...")
    app.run()
