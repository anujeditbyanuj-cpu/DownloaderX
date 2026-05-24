# 🎬 YouTube Downloader Bot

Telegram bot with YouTube search, inline quality buttons, 2GB upload, auto split, cookies bypass.

## ✨ Features
| | Feature |
|---|---|
| 🔍 | YouTube search (8 results with inline buttons) |
| 🎬 | Inline quality buttons: 1080p / 720p / 480p / 360p / 144p |
| 🎵 | MP3 quality selection: 128 / 192 / 320 kbps |
| 🖼 | Thumbnail preview before download |
| 📝 | Video description button |
| 📊 | Live progress bar with speed & ETA |
| 🍪 | Cookies support (age-restrict / login bypass) |
| 📦 | 2 GB Telegram upload support |
| ✂️ | Auto split files > 2GB into chunks |
| 📋 | Playlist/channel with range |
| ❌ | /cancel anytime |

## 🚀 Quick Start
```bash
git clone https://github.com/yourname/yt-dl-bot
cd yt-dl-bot
pip install -r requirements.txt
sudo apt install ffmpeg
cp .env.example .env
# Fill API_ID, API_HASH, BOT_TOKEN in .env
python bot.py
```

## 🍪 Cookies Setup
1. Install **"Get cookies.txt LOCALLY"** in Chrome
2. Open youtube.com (logged in)
3. Click extension → Export → save as `cookies.txt` in bot folder

## 💬 Commands
| Command | Description |
|---|---|
| `/search <query>` | Search YouTube, pick from 20 results |
| `/setformat [mp3_128\|mp3_192\|mp3_320\|360\|480\|720\|1080]` | Set default playlist format |
| `/channel @handle [1-10]` | Download channel range |
| `/cancel` | Stop active download |

## 📋 Playlist Range
```
https://youtube.com/playlist?list=XXX | 1-50
```

## 🐳 Docker
```bash
cp .env.example .env
docker build -t yt-bot .
docker run -d --env-file .env -v $(pwd)/cookies.txt:/app/cookies.txt yt-bot
```

## ☁️ Render Deployment
1. Push code to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your repo
4. Settings:
   - **Environment:** Docker  
   - **Health Check Path:** `/health`
5. Add environment variables (`API_ID`, `API_HASH`, `BOT_TOKEN`)
6. Deploy — Render auto-sets `PORT`, Flask picks it up automatically

**Endpoints after deploy:**
| URL | Description |
|---|---|
| `/` | Bot info + uptime |
| `/health` | Health check (Render uses this) |
| `/stats` | Active downloads, pending URLs |


## 📁 Files
```
├── bot.py          Main bot (commands, callbacks, progress, upload)
├── downloader.py   yt-dlp wrapper with cookies + 2GB support
├── search.py       YouTube search via yt-dlp
├── utils.py        Playlist URL fetch + file splitter
├── config.py       .env loader
├── requirements.txt
├── Dockerfile
└── .env.example
```
