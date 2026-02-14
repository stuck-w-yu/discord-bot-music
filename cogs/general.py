import discord
from discord.ext import commands
import psutil
import platform
import datetime
import time

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


    @commands.command(name='svlogs', aliases=['serverstats', 'sysinfo'])
    async def svlogs(self, ctx):
        """Displays server system statistics."""
        async with ctx.typing():
            # System Info
            uname = platform.uname()
            system_os = f"{uname.system} {uname.release}"
            node_name = uname.node
            python_version = platform.python_version()
            
            # CPU
            cpu_usage = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count(logical=True)
            
            # Memory
            svmem = psutil.virtual_memory()
            mem_total = f"{svmem.total / (1024 ** 3):.2f} GB"
            mem_available = f"{svmem.available / (1024 ** 3):.2f} GB"
            mem_used = f"{svmem.used / (1024 ** 3):.2f} GB"
            mem_percent = svmem.percent

            # Disk
            disk_usage = psutil.disk_usage('/')
            disk_total = f"{disk_usage.total / (1024 ** 3):.2f} GB"
            disk_used = f"{disk_usage.used / (1024 ** 3):.2f} GB"
            disk_percent = disk_usage.percent
            
            # Uptime
            boot_time_timestamp = psutil.boot_time()
            bt = datetime.datetime.fromtimestamp(boot_time_timestamp)
            uptime = datetime.datetime.now() - bt
            
            embed = discord.Embed(title="🖥️ Server Statistics", color=discord.Color.from_rgb(46, 204, 113))
            
            embed.add_field(name="💻 System Info", value=f"**OS**: {system_os}\n**Node**: {node_name}\n**Python**: {python_version}", inline=False)
            embed.add_field(name="🧠 CPU Usage", value=f"**Usage**: {cpu_usage}%\n**Cores**: {cpu_count}", inline=True)
            embed.add_field(name="💾 RAM Usage", value=f"**Used**: {mem_used} / {mem_total} ({mem_percent}%)", inline=True)
            embed.add_field(name="💿 Disk Usage", value=f"**Used**: {disk_used} / {disk_total} ({disk_percent}%)", inline=True)
            embed.add_field(name="⏱️ Uptime", value=str(uptime).split('.')[0], inline=False)
            
            embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
            
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
            "`!nowplaying (np)` - Lagu yang sedang diputar\n"
            "`!skip (s) [index]` - Lewati lagu (opsional: ke urutan tertentu)\n"
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
