# Discord Music Bot

A feature-rich Discord bot for playing music and tracking user levels.

## Features
- 🎵 High-quality music playback from YouTube & Spotify
- 📈 Leveling system with text & voice XP
- ⏯️ Music controls (Play, Pause, Skip, Stop, Queue)
- 📝 User profiles and leaderboards
- 🐳 Docker support for easy deployment

## Setup
1. Clone the repository
2. Create a `.env` file with your `DISCORD_TOKEN`
3. Install dependencies: `pip install -r requirements.txt`
4. Run the bot: `python main.py`

## Docker Deployment (Recommended)
To ensure data persistence (levels, XP) across restarts, use Docker Compose:

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

## Deploying on Coolify (Dockerfile Only)
If you prefer using just the `Dockerfile`:

1. Create a new resource -> **Git Repository**.
2. Select this repository.
3. **Build Pack**: Select **Dockerfile**.
4. **CRITICAL**: Go to the **Storage** tab in Coolify.
   - Add a new volume.
   - **Volume Name**: `discord-bot-data` (or similar)
   - **Destination Path**: `/app/data`
   
   *One-time setup: If you forgot this step and the bot restarts, levels will be lost.*

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
- `!level` (lvl) - Check your level and XP
- `!leaderboard` (lb) - View server leaderboard
- `!xyzprofile` (pf) - View rich profile card
