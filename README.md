# Discord Music Bot

A feature-rich Discord bot for playing music.

## 🍪 Fixing YouTube Sign-in Errors
If you see errors like `Sign in to confirm you’re not a bot`, you need to provide a `cookies.txt` file.
1.  Install a browser extension to export cookies (e.g., "Get cookies.txt LOCALLY" for Chrome/Firefox).
2.  Go to YouTube and make sure you are logged in.
3.  Use the extension to export your cookies as a file named `cookies.txt`.
4.  Place `cookies.txt` in the same directory as `main.py`.
5.  Restart the bot.

### ☁️ Deploying on Coolify / Docker
If you are deploying on Coolify or Docker, you can use an Environment Variable instead of a file:
1.  Open your project in Coolify.
2.  Go to **Environment Variables**.
3.  Add a new variable:
    -   **Key**: `YOUTUBE_COOKIES`
    -   **Value**: (Paste the entire content of your `cookies.txt` file here)
4.  Redeploy/Restart the bot.

## 🛠️ Usage
- 🎵 High-quality music playback from YouTube & Spotify (metadata search)
- ⏯️ Music controls (Play, Pause, Skip, Stop, Queue)
- 🐳 Docker support for easy deployment

## Lavalink Mode (Recommended for Stability)
Bot ini sekarang mendukung 2 mode music player:
1. Legacy mode (`cogs/music.py`) - FFmpeg + yt-dlp langsung.
2. Lavalink mode (`cogs/music_lavalink.py`) - playback diproses oleh Lavalink server.

Aktifkan Lavalink mode dengan env:
- `USE_LAVALINK=true`
- `LAVALINK_HOST=lavalink`
- `LAVALINK_PORT=2333`
- `LAVALINK_PASSWORD=youshallnotpass`

Catatan Spotify:
- Spotify tidak di-stream langsung (DRM).
- Bot membaca metadata lagu Spotify (judul + artis), lalu mencari sumber playable (YouTube) untuk diputar via Lavalink.

## Setup
1. Clone the repository
2. Create a `.env` file with your `DISCORD_TOKEN`
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python main.py`

## Docker Deployment (Recommended)
To ensure data persistence across restarts, use Docker Compose:

1. Build and start the container:
   ```bash
   docker-compose up -d
   ```
2. View logs:
   ```bash
   docker-compose logs -f
   ```
3. Update the bot:
   ```bash
   docker-compose build --no-cache
   docker-compose up -d
   ```

Compose di repository ini sudah menyertakan service `lavalink`, jadi cukup `docker-compose up -d` untuk menjalankan bot + lavalink sekaligus.

## Deploying on Coolify (Dockerfile Only)
If you prefer using just the `Dockerfile`:

1. Create a new resource -> **Git Repository**.
2. Select this repository.
3. **Build Pack**: Select **Dockerfile**.
4. **CRITICAL**: Go to the **Storage** tab in Coolify.
   - Add a new volume.
   - **Volume Name**: `discord-bot-data` (or similar)
   - **Destination Path**: `/app/data`
   
   *One-time setup: If you forgot this step and the bot restarts, runtime data will be lost.*

## Commands
- `!play <song/url>` (p) - Play a song or playlist (YouTube/Spotify)
- `!pause` (ps) - Pause playback
- `!resume` (res) - Resume playback
- `!nowplaying` (np) - Show current song and progress
- `!skip <index>` (s) - Skip current song (or skip to specific queue number)
- `!stop` (st) - Stop playback and clear queue
- `!queue` (q) - Show current queue
- `!loop` (lp) - Toggle loop mode (Off -> Current -> Queue)
- `!volume <0-100>` (v) - Set volume
- `!join` (j) / `!leave` (l) - Join/Leave voice channel
- `!svlogs` (serverstats) - View server statistics & system info
