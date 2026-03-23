import discord
from discord.ext import commands
import asyncio
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
        # Check if psutil is available
        try:
            import psutil
        except ImportError:
            return await ctx.send("❌ Error: `psutil` library is not installed. Please install it using `pip install psutil`.")

        async with ctx.typing():
            # Run blocking psutil calls in executor
            def get_stats(*args):
                # System Info
                uname = platform.uname()
                system_os = f"{uname.system} {uname.release}"
                node_name = uname.node
                python_version = platform.python_version()
                
                # CPU (blocking)
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
                
                return {
                    "os": system_os, "node": node_name, "py": python_version,
                    "cpu_u": cpu_usage, "cpu_c": cpu_count,
                    "mem_used": mem_used, "mem_total": mem_total, "mem_p": mem_percent,
                    "disk_used": disk_used, "disk_total": disk_total, "disk_p": disk_percent,
                    "uptime": str(uptime).split('.')[0]
                }
            
            # Execute in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(None, get_stats)
            
            embed = discord.Embed(title="🖥️ Server Statistics", color=discord.Color.from_rgb(46, 204, 113))
            
            embed.add_field(name="💻 System Info", value=f"**OS**: {stats['os']}\n**Node**: {stats['node']}\n**Python**: {stats['py']}", inline=False)
            embed.add_field(name="🧠 CPU Usage", value=f"**Usage**: {stats['cpu_u']}%\n**Cores**: {stats['cpu_c']}", inline=True)
            embed.add_field(name="💾 RAM Usage", value=f"**Used**: {stats['mem_used']} / {stats['mem_total']} ({stats['mem_p']}%)", inline=True)
            embed.add_field(name="💿 Disk Usage", value=f"**Used**: {stats['disk_used']} / {stats['disk_total']} ({stats['disk_p']}%)", inline=True)
            embed.add_field(name="⏱️ Uptime", value=stats['uptime'], inline=False)
            
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
            "3. Nikmati musik!"
        )
        embed.add_field(name="📖 Cara Penggunaan", value=guide, inline=False)

        # Music
        music_cmds = (
            "`!play (p)` - Memutar lagu/playlist\n"
            "`!pause (ps)` - Jeda lagu\n"
            "`!resume (res)` - Lanjut lagu\n"
            "`!nowplaying (np)` - Lagu yang sedang diputar\n"
            "`!skip (s) [index]` - Lewati lagu (opsional: ke urutan tertentu)\n"
            "`!remove (r) <index|clear [index]>` - Hapus lagu dari queue\n"
            "`!clear (cq)` - Bersihkan queue dengan cepat\n"
            "`!stop (st)` - Stop & bersihkan queue\n"
            "`!queue (q)` - Lihat antrian\n"
            "`!loop (lp)` - Mode Loop\n"
            "`!volume (v, vol)` - Atur volume (0-100)\n"
            "`!join (j)` / `!leave (l)`"
        )
        embed.add_field(name="🎵 Music", value=music_cmds, inline=False)
        
        # General
        general_cmds = (
            "`!dev (about)` - Info Developer\n"
            "`!setname (nick)` - Ganti nama bot\n"
            "`!resetname` - Reset nama bot\n"
            "`!ping` - Cek latency\n"
            "`!svlogs (serverstats)` - Cek statistik server"
        )
        embed.add_field(name="⚙️ General", value=general_cmds, inline=False)
        
        embed.set_footer(text="Dibuat dengan kebanggaan oleh, Wahyu Firmansyah")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(General(bot))
