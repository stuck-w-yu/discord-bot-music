import discord
from discord.ext import commands
import aiosqlite
import time
import os

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {} # {member_id: join_timestamp}

    async def cog_load(self):
        async with aiosqlite.connect('leveling.db') as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    total_time INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0,
                    songs_played INTEGER DEFAULT 0
                )
            ''')
            # Attempt migration for existing DBs
            try:
                await db.execute('ALTER TABLE user_stats ADD COLUMN songs_played INTEGER DEFAULT 0')
            except Exception:
                pass # Column likely exists
            await db.commit()
        print("Leveling Database Initialized")

    async def increment_songs_played(self, user_id, guild_id):
        async with aiosqlite.connect('leveling.db') as db:
            cursor = await db.execute('SELECT songs_played FROM user_stats WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            
            if row:
                songs_played = row[0] + 1
                await db.execute('UPDATE user_stats SET songs_played = ? WHERE user_id = ?', (songs_played, user_id))
            else:
                # Initialize user if playing song before joining voice? Unlikely but possible.
                await db.execute('INSERT INTO user_stats (user_id, guild_id, total_time, level, xp, songs_played) VALUES (?, ?, 0, 1, 0, 1)', (user_id, guild_id))
            
            await db.commit()

    @commands.Cog.listener()
    async def on_ready(self):
        # Scan for users already in voice channels
        print("Scanning voice channels...")
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if not member.bot and member.id not in self.voice_states:
                        self.voice_states[member.id] = int(time.time())
                        print(f"Tracking existing user: {member.name}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # Join Voice Channel
        if not before.channel and after.channel:
            self.voice_states[member.id] = int(time.time())
            print(f"DEBUG: {member.name} joined voice.")

        # Leave Voice Channel
        elif before.channel and not after.channel:
            if member.id in self.voice_states:
                join_time = self.voice_states.pop(member.id)
                duration = int(time.time()) - join_time
                if duration > 0:
                     await self.update_stats(member, duration)
                print(f"DEBUG: {member.name} left voice. Duration: {duration}s")
            else:
                 print(f"DEBUG: {member.name} left voice but no join time recorded.")
        
        # Switched channel - technically online time continues, so we do nothing unless we want to track per-channel
        # If user behaves: Join A -> Switch B -> Leave B.
        # Join A: record time. Switch B: before.channel=A, after.channel=B. 
        # Logic above handles !before and after for JOIN, before and !after for LEAVE. 
        # Switch doesn't trigger either. So timer continues. Correct.

    async def update_stats(self, member, duration):
        async with aiosqlite.connect('leveling.db') as db:
            cursor = await db.execute('SELECT total_time FROM user_stats WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

            if row:
                total_time = row[0] + duration
            else:
                total_time = duration

            # Calculate Level: 1 hour = 1 Level. Cap at 100.
            # Level 1 is 0 hours. Level 2 is 1 hour.
            # Formula: Level = 1 + floor(hours).
            level = 1 + int(total_time / 3600)
            if level > 100: level = 100
            
            if row:
                await db.execute('UPDATE user_stats SET total_time = ?, level = ? WHERE user_id = ?', (total_time, level, member.id))
            else:
                await db.execute('INSERT INTO user_stats (user_id, guild_id, total_time, level) VALUES (?, ?, ?, ?)', (member.id, member.guild.id, total_time, level))

            await db.commit()
            
    @commands.command(name='level')
    async def level(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        async with aiosqlite.connect('leveling.db') as db:
            cursor = await db.execute('SELECT total_time, level FROM user_stats WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if row:
            total_time, level = row
            hours = total_time // 3600
            minutes = (total_time % 3600) // 60
            
            embed = discord.Embed(title=f"{member.name}'s Stats", color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Level", value=str(level), inline=True)
            embed.add_field(name="Total Online Time", value=f"{hours}h {minutes}m", inline=True)
            
            # Progress bar to next level?
            # Next level at (level) * 3600 seconds. 
            # Current value: total_time.
            # Next Level Threshold: (hours + 1) * 3600
            # Wait, level = 1 + total_time/3600.
            # If total_time = 3599, level 1. Next level at 3600.
            # Progress: (total_time % 3600) / 3600
            
            next_level_seconds = 3600
            current_progress = total_time % 3600
            percent = int((current_progress / next_level_seconds) * 10) # 0-10 scale
            bar = "🟩" * percent + "⬜" * (10 - percent)
            
            embed.add_field(name="Progress to Next Level", value=f"{bar} {int((current_progress/next_level_seconds)*100)}%", inline=False)
            
            await ctx.send(embed=embed)
        else:
             await ctx.send(f"❌ {member.name} has no stats recorded yet.")

    async def generate_profile_embed(self, member):
        async with aiosqlite.connect('leveling.db') as db:
            cursor = await db.execute('SELECT total_time, level, xp, songs_played FROM user_stats WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if row:
            total_time, level, xp, songs_played = row
        else:
            total_time, level, xp, songs_played = 0, 1, 0, 0

        hours = total_time // 3600
        minutes = (total_time % 3600) // 60
        
        next_level_seconds = 3600
        current_progress = total_time % 3600
        percent = int((current_progress / next_level_seconds) * 10)
        bar = "🟩" * percent + "⬜" * (10 - percent)
        percentage = int((current_progress/next_level_seconds)*100)

        embed = discord.Embed(color=discord.Color.from_str("#FD0061"))
        embed.set_author(name=f"{member.name}'s Profile", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="🎤 Voice Time", value=f"**{hours}h {minutes}m**", inline=True)
        embed.add_field(name="🎵 Songs Played", value=f"**{songs_played}**", inline=True)
        embed.add_field(name="🆙 Level", value=f"**{level}**", inline=True)
        
        embed.add_field(name="✨ XP Progress", value=f"`[{bar}]` **{percentage}%**", inline=False)
        
        embed.set_footer(text="XYZ Profile System • Level Up by chatting!", icon_url=self.bot.user.display_avatar.url)
        return embed

    @commands.command(name='xyzprofile')
    async def xyzprofile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = await self.generate_profile_embed(member)
        view = ProfileView(self, member)
        await ctx.send(embed=embed, view=view)

class ProfileView(discord.ui.View):
    def __init__(self, cog, member):
        super().__init__(timeout=None)
        self.cog = cog
        self.member = member

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, custom_id="profile_refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Refresh the embed
        embed = await self.cog.generate_profile_embed(self.member)
        await interaction.response.edit_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Leveling(bot))
