import discord
from discord.ext import commands
import os
import asyncio
import traceback
import socket
import aiohttp
import static_ffmpeg
from dotenv import load_dotenv

load_dotenv()
load_dotenv(dotenv_path='environment/.env', override=False)
static_ffmpeg.add_paths()

TOKEN = os.getenv('DISCORD_TOKEN')
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')


def _cookies_configured() -> bool:
    data_dir = os.getenv('DATA_DIR', 'data')
    data_cookie_path = os.path.join(data_dir, 'cookies.txt')

    cookie_file_env = (
        os.getenv('YOUTUBE_COOKIES_FILE')
        or os.getenv('COOKIE_FILE')
        or os.getenv('YTDLP_COOKIEFILE')
    )
    youtube_cookies = os.getenv('YOUTUBE_COOKIES', '').strip()

    if os.path.exists(data_cookie_path):
        return True
    if os.path.exists('cookies.txt'):
        return True
    if cookie_file_env and os.path.exists(cookie_file_env):
        return True
    if youtube_cookies:
        return True
    return False

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        # Disable default help command to avoid conflict with custom help
        super().__init__(command_prefix='!', intents=intents, help_command=None)
        # Explicitly remove help command just in case
        self.remove_command('help')

    async def setup_hook(self):
        use_lavalink = os.getenv('USE_LAVALINK', 'false').lower() == 'true'
        force_lavalink = os.getenv('FORCE_LAVALINK', 'false').lower() == 'true'

        # Lavalink does not use yt-dlp cookiefile; prefer legacy when cookies are configured.
        if use_lavalink and _cookies_configured() and not force_lavalink:
            use_lavalink = False
            print('YouTube cookies detected. Switching to legacy music cog so cookies are used.')
            print('Set FORCE_LAVALINK=true to keep Lavalink mode and ignore cookies.')

        if use_lavalink:
            await self.load_extension('cogs.music_lavalink')
            print('Loaded Lavalink music cog (cogs.music_lavalink).')
        else:
            await self.load_extension('cogs.music')
            print('Loaded legacy music cog (cogs.music).')
        await self.load_extension('cogs.general')
        print("Music and General Cogs Loaded")

    async def on_ready(self):
        print(f'Logged in as {self.user.name} ({self.user.id})')
        print('------')

    async def on_command_error(self, ctx, error):
        # Get context info
        user = f"{ctx.author} ({ctx.author.id})"
        command = ctx.command.qualified_name if ctx.command else "Unknown"
        content = ctx.message.content

        if isinstance(error, commands.CommandNotFound):
            print(f"[ERROR] User: {user} | Command: {content} | Error: Command not found")
            normalized = content.lower().strip()
            if normalized.startswith(("!r cl", "!r clear", "!r remove")):
                await ctx.send(
                    "Perintah itu tidak tersedia di bot ini. "
                    "Gunakan `!remove <index>` atau `!remove clear [index]` untuk hapus dari antrean."
                )

        elif isinstance(error, commands.MissingRequiredArgument):
            print(f"[ERROR] User: {user} | Command: {command} | Error: Missing argument {error.param}")
            await ctx.send(f"❌ **Missing Required Argument**: `{error.param}`\nUsage: `{ctx.prefix}{command} {ctx.command.signature}`")

        elif isinstance(error, commands.BadArgument):
            print(f"[ERROR] User: {user} | Command: {command} | Error: Bad argument - {error}")
            await ctx.send(f"❌ **Invalid Argument**: Please check your input.\nUsage: `{ctx.prefix}{command} {ctx.command.signature}`")

        elif isinstance(error, commands.CheckFailure):
            print(f"[ERROR] User: {user} | Command: {command} | Error: Check failure - {error}")
            await ctx.send("🚫 You do not have permission to use this command.")

        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            network_markers = (
                "ClientConnectorDNSError",
                "Temporary failure in name resolution",
                "socket.gaierror",
                "Cannot connect to host",
            )
            if any(marker in str(original) for marker in network_markers):
                 await ctx.send(
                     "⚠️ **Network Error**: Could not connect to Discord voice servers (temporary DNS issue).\n"
                     "Please try:\n"
                     "1. Restarting the bot/container.\n"
                     "2. Checking server internet and DNS resolver.\n"
                     "3. Waiting a few minutes; auto-retry is enabled."
                 )
                 print(f"[CRITICAL] User: {user} | Command: {command} | DNS Error: {original}")
            else:
                await ctx.send(f"⚠️ An error occurred: {original}")
                print(f"[ERROR] User: {user} | Command: {command} | Invoke Error: {original}")
                traceback.print_exception(type(original), original, original.__traceback__)
        else:
            await ctx.send(f"❌ Error: {error}")
            print(f"[ERROR] User: {user} | Command: {content} | Unhandled Error: {error}")
            traceback.print_exception(type(error), error, error.__traceback__)

bot = MusicBot()

async def run_bot_with_retry() -> None:
    if not TOKEN or TOKEN == "your_token_here":
        print("ERROR: Please set your DISCORD_TOKEN in the .env file.")
        return

    attempt = 0
    while True:
        try:
            await bot.start(TOKEN)
            break
        except discord.LoginFailure:
            print("ERROR: Invalid DISCORD_TOKEN. Please check your .env file.")
            break
        except (aiohttp.ClientConnectorError, socket.gaierror, asyncio.TimeoutError) as e:
            attempt += 1
            backoff = min(300, 5 * (2 ** min(attempt, 6)))
            print(
                f"Network/DNS error while connecting to Discord (attempt {attempt}): {e}. "
                f"Retrying in {backoff}s..."
            )
            await asyncio.sleep(backoff)
        except KeyboardInterrupt:
            print("Bot shutdown initiated gracefully...")
            break
        except Exception as e:
            attempt += 1
            backoff = min(120, 5 * (2 ** min(attempt, 4)))
            print(f"Fatal startup error (attempt {attempt}): {e}. Retrying in {backoff}s...")
            traceback.print_exception(type(e), e, e.__traceback__)
            await asyncio.sleep(backoff)
        finally:
            if not bot.is_closed():
                await bot.close()


if __name__ == "__main__":
    asyncio.run(run_bot_with_retry())
