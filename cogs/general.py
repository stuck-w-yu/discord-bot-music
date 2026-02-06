import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='setname')
    @commands.has_permissions(manage_nicknames=True)
    async def setname(self, ctx, *, name: str):
        """Changes the bot's nickname in the current server."""
        try:
            await ctx.guild.me.edit(nick=name)
            await ctx.send(f"✅ Nickname changed to: **{name}**")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to change my nickname!")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {e}")

    @commands.command(name='resetname')
    @commands.has_permissions(manage_nicknames=True)
    async def resetname(self, ctx):
        """Resets the bot's nickname to the global username."""
        try:
            await ctx.guild.me.edit(nick=None)
            await ctx.send("✅ Nickname reset to default!")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to change my nickname!")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {e}")

async def setup(bot):
    await bot.add_cog(General(bot))
