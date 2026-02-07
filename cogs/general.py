import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ping', aliases=['latency'])
    async def ping(self, ctx):
        """Checks the bot's latency."""
        latency = round(self.bot.latency * 1000)
        await ctx.send(f'🏓 Pong! Latency: **{latency}ms**')

    @commands.command(name='setname', aliases=['nick'])
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

    @commands.command(name='resetname', aliases=['resetnick'])
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

    @commands.command(name='dev', aliases=['about'])
    async def dev(self, ctx):
        """Shows information about the developer."""
        embed = discord.Embed(title="Halo! 👋", color=discord.Color.gold())
        
        embed.description = (
            "Kenalin, aku **Wahyu Firmansyah**, developer di balik bot ini! 🚀\n"
            "Aku suka coding dan bikin hal-hal seru di internet.\n\n"
            "👇 **Stalk me here:**\n"
            "📸 **Instagram:** [Klik Disini](https://www.instagram.com/stuckw.yu_)\n"
            "🌐 **Website:** [wahyufirmansyah.my.id](https://wahyufirmansyah.my.id)\n"
            "🌐 **Website:** [Fedora Aliansi Digital](https://fedoraweb.site)"
        )
        
        embed.set_footer(text="Jangan lupa follow ya! 😉")
        
        await ctx.send(embed=embed)

    @commands.command(name='help', aliases=['h'])
    async def help(self, ctx):
        """Shows header with commands"""
        embed = discord.Embed(title="🤖 Bot Help Menu", description="Daftar perintah yang tersedia. Gunakan alias dalam kurung (...) untuk lebih cepat!", color=discord.Color.gold())
        
        # Guide
        guide = (
            "1. Masuk ke Voice Channel.\n"
            "2. Ketik `!p <judul lagu>` untuk memutar musik.\n"
            "3. Nikmati musik dan dapatkan XP!"
        )
        embed.add_field(name="📖 Cara Penggunaan", value=guide, inline=False)

        # Music
        music_cmds = (
            "`!play (p)` - Memutar lagu/playlist\n"
            "`!pause (ps)` - Jeda lagu\n"
            "`!resume (res)` - Lanjut lagu\n"
            "`!skip (s)` - Lewati lagu\n"
            "`!stop (st)` - Stop & bersihkan queue\n"
            "`!queue (q)` - Lihat antrian\n"
            "`!loop (lp)` - Mode Loop\n"
            "`!volume (v, vol)` - Atur volume (0-100)\n"
            "`!join (j)` / `!leave (l)`"
        )
        embed.add_field(name="🎵 Music", value=music_cmds, inline=False)
        
        # Leveling
        level_cmds = (
            "`!level (lvl)` - Cek level & XP\n"
            "`!xyzprofile (pf)` - Lihat profil\n"
            "`!leaderboard (lb, top)` - Top 10 users"
        )
        embed.add_field(name="📊 Leveling", value=level_cmds, inline=False)
        
        # General
        general_cmds = (
            "`!dev (about)` - Info Developer\n"
            "`!setname (nick)` - Ganti nama bot\n"
            "`!resetname` - Reset nama bot\n"
            "`!ping` - Cek latency"
        )
        embed.add_field(name="⚙️ General", value=general_cmds, inline=False)
        
        embed.set_footer(text="Dibuat dengan kebanggaan oleh, Wahyu Firmansyah")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
