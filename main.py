import discord
from discord.ext import commands
import os
import asyncio
import static_ffmpeg
from dotenv import load_dotenv

load_dotenv()
static_ffmpeg.add_paths()

TOKEN = os.getenv('DISCORD_TOKEN')

class MusicBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents, help_command=commands.DefaultHelpCommand())

    async def setup_hook(self):
        await self.load_extension('cogs.music')
        await self.load_extension('cogs.leveling')
        print("Music and Leveling Cogs Loaded")

    async def on_ready(self):
        print(f'Logged in as {self.user.name} ({self.user.id})')
        print('------')

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandInvokeError):
            original = error.original
            if "ClientConnectorDNSError" in str(original):
                 await ctx.send("⚠️ **Network Error**: Could not connect to Discord voice servers. This is likely a DNS issue. Please try:\n1. Restarting the bot.\n2. Checking your internet connection.\n3. Flushing your DNS (`ipconfig /flushdns`).")
                 print(f"DNS Error detected: {original}")
            else:
                await ctx.send(f"An error occurred: {original}")
                print(f"Command Error: {error}")
        else:
            await ctx.send(f"Error: {error}")
            print(f"Unhandled Error: {error}")

bot = MusicBot()

if __name__ == "__main__":
    if not TOKEN or TOKEN == "your_token_here":
        print("ERROR: Please set your DISCORD_TOKEN in the .env file.")
    else:
        bot.run(TOKEN)
