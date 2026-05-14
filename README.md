# Discord Music Bot

A feature-rich Discord bot for playing music, with support for both legacy `yt-dlp` and modern Lavalink playback.

## 🎶 Player Modes

This bot supports two different music playback modes:

1.  **Lavalink Mode (Default & Recommended)**
    -   Uses a dedicated Lavalink server to handle music processing.
    -   More stable, better performance, and avoids most YouTube rate-limiting/blocking issues.
    -   Activated by default in the provided `docker-compose.yml`.
    -   **Does NOT require YouTube cookies.**

2.  **Legacy Mode**
    -   Uses `yt-dlp` and `FFmpeg` directly on the bot's machine.
    -   Simpler setup for local testing but prone to YouTube errors (`Sign in to confirm you’re not a bot`).
    -   **Requires YouTube cookies** to function reliably.

---

## 🛠️ Configuration

### Environment Variables

Create a `.env` file in the root directory or set these in your deployment environment (e.g., Docker, Coolify).

| Variable                | Description                                                                    | Mode      |
| ----------------------- | ------------------------------------------------------------------------------ | --------- |
| `DISCORD_TOKEN`         | **Required.** Your Discord bot token.                                          | Both      |
| `USE_LAVALINK`          | Set to `true` to enable Lavalink mode. Defaults to `false` (legacy).           | Both      |
| `FORCE_LAVALINK`        | Optional. Set `true` to force Lavalink even when YouTube cookies are detected.  | Both      |
| `LAVALINK_HOST`         | Hostname for the Lavalink server.                                              | Lavalink  |
| `LAVALINK_PORT`         | Port for the Lavalink server.                                                  | Lavalink  |
| `LAVALINK_PASSWORD`     | Password for the Lavalink server.                                              | Lavalink  |
| `SPOTIPY_CLIENT_ID`     | Optional. Your Spotify App Client ID for better Spotify metadata searching.    | Both      |
| `SPOTIPY_CLIENT_SECRET` | Optional. Your Spotify App Client Secret.                                      | Both      |
| `YOUTUBE_COOKIES`       | **Legacy Mode Only.** Content of your `cookies.txt` file to bypass YT errors.  | Legacy    |
| `YOUTUBE_COOKIES_FILE`  | **Legacy Mode Only.** Alternative to `YOUTUBE_COOKIES`. Path to a cookie file. | Legacy    |
| `DATA_DIR`              | Optional. Directory to store persistent data like queues. Defaults to `data`.  | Both      |

### 🍪 YouTube Cookies (Legacy Mode Only)

If cookies are detected (`data/cookies.txt`, `cookies.txt`, `YOUTUBE_COOKIES_FILE`, or `YOUTUBE_COOKIES`), the bot will automatically switch from Lavalink mode to Legacy mode so cookies can be used. Set `FORCE_LAVALINK=true` to disable this auto-switch.

If you are running in **Legacy Mode** (`USE_LAVALINK=false`) and see errors like `Sign in to confirm you’re not a bot`, you must provide YouTube cookies.

**1. Using a `cookies.txt` file:**
   - Install a browser extension to export cookies (e.g., "Get cookies.txt LOCALLY").
   - Go to YouTube, log in, and export your cookies as `cookies.txt`.
   - Place the file in the `data` directory (or the path specified by `DATA_DIR`).

**2. Using Environment Variables:**
   - **`YOUTUBE_COOKIES`**: Paste the entire content of your `cookies.txt` file into this variable. It supports plain text, single-line escaped newlines (`\n`), or base64-encoded content (e.g., `base64:<encoded_content>`).
   - **`YOUTUBE_COOKIES_FILE`**: Provide the full path to your cookie file (e.g., `/app/data/cookies.txt`). This is the recommended method for Docker/Coolify.

---

## 🚀 Deployment

### Docker Deployment (Recommended)

The provided `docker-compose.yml` is the easiest way to deploy the bot. It starts both the bot and a Lavalink server.

**By default, it runs in Lavalink Mode.**

1.  **Build and start the containers:**
    ```bash
    docker-compose up -d
    ```
2.  **View logs:**
    ```bash
    docker-compose logs -f
    ```
3.  **Update the bot:**
    ```bash
    docker-compose build --no-cache
    docker-compose up -d
    ```

The Compose file is pre-configured with a public DNS (`1.1.1.1`, `8.8.8.8`) to improve DNS stability and prevent `Temporary failure in name resolution` errors.

### Local Setup (Legacy Mode)

1.  Clone the repository.
2.  Create a `.env` file with your `DISCORD_TOKEN`.
3.  Install dependencies: `pip install -r requirements.txt`.
4.  (Optional but Recommended) Provide YouTube cookies as described above.
5.  Run the bot: `python main.py`.

### Deploying on Coolify (Dockerfile)

1.  Create a new resource -> **Git Repository**.
2.  Select this repository.
3.  **Build Pack**: Select **Dockerfile**.
4.  Configure your environment variables as needed.
5.  **CRITICAL (Storage)**: Go to the **Storage** tab.
    -   Add a new volume.
    -   **Destination Path**: `/app/data` (This ensures your queue and other data persist across restarts).

## Commands
- `!play <song/url>` (p) - Play a song or playlist (YouTube/Spotify)
- `!pause` (ps) - Pause playback
- `!resume` (res) - Resume playback
- `!nowplaying` (np) - Show current song and progress
- `!skip <index>` (s) - Skip current song (or skip to specific queue number)
- `!remove <index|clear [index]>` (r, rm) - Remove song from queue / compatibility for old `!r cl <index>` style
- `!clear` (cq, clearqueue) - Clear all songs in queue quickly
- `!stop` (st) - Stop playback and clear queue
- `!queue` (q) - Show current queue
- `!loop` (lp) - Toggle loop mode (Off -> Current -> Queue)
- `!volume <0-100>` (v) - Set volume
- `!join` (j) / `!leave` (l) - Join/Leave voice channel
- `!svlogs` (serverstats) - View server statistics & system info
