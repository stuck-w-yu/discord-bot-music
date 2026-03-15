import discord
from discord.ext import commands
import os
import asyncio
import static_ffmpeg
from dotenv import load_dotenv

load_dotenv()
static_ffmpeg.add_paths()

TOKEN = os.getenv('DISCORD_TOKEN')
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')

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
        if use_lavalink:
            await self.load_extension('cogs.music_lavalink')
            print('Loaded Lavalink music cog (cogs.music_lavalink).')
        else:
            await self.load_extension('cogs.music')
            print('Loaded legacy music cog (cogs.music).')
        await self.load_extension('cogs.leveling')
        await self.load_extension('cogs.general')
        print("Music and Leveling Cogs Loaded")

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
            if "ClientConnectorDNSError" in str(original):
                 await ctx.send("⚠️ **Network Error**: Could not connect to Discord voice servers. This is likely a DNS issue. Please try:\n1. Restarting the bot.\n2. Checking your internet connection.\n3. Flushing your DNS (`ipconfig /flushdns`).")
                 print(f"[CRITICAL] User: {user} | Command: {command} | DNS Error: {original}")
            else:
                await ctx.send(f"⚠️ An error occurred: {original}")
                print(f"[ERROR] User: {user} | Command: {command} | Invoke Error: {original}")
        else:
            await ctx.send(f"❌ Error: {error}")
            print(f"[ERROR] User: {user} | Command: {content} | Unhandled Error: {error}")

bot = MusicBot()

if __name__ == "__main__":
    if not TOKEN or TOKEN == "your_token_here":
        print("ERROR: Please set your DISCORD_TOKEN in the .env file.")
    else:
        try:
            bot.run(TOKEN)
        except KeyboardInterrupt:
            print("Bot shutdown initiated gracefully...")
        except Exception as e:
            print(f"Fatal error: {e}")
