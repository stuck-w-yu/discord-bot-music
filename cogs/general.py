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

    @commands.command(name='dev')
    async def dev(self, ctx):
        """Shows information about the developer."""
        embed = discord.Embed(title="Halo! 👋", color=discord.Color.gold())
        
        embed.description = (
            "Kenalin, aku **Wahyu Firmansyah**, developer di balik bot ini! 🚀\n"
            "Aku suka coding dan bikin hal-hal seru di internet.\n\n"
            "👇 **Stalk me here:**\n"
            "📸 **Instagram:** [Klik Disini](https://www.instagram.com/stuckw.yu_)\n"
            "🌐 **Website:** [wahyufirmansyah.my.id](https://wahyufirmansyah.my.id)"
        )
        
        embed.set_footer(text="Jangan lupa follow ya! 😉")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
