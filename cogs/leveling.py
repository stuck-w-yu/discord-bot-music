import discord
from discord.ext import commands, tasks
import aiosqlite
import time
import os
import random

# Constants
VOICE_XP_PER_TICK = 1  # 5 seconds = 1 XP => 12 XP/min
VOICE_TIME_PER_TICK = 5 # 5 seconds
CHAT_XP_RANGE = (15, 25)
CHAT_COOLDOWN = 60
XP_PER_LEVEL = 600

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_cooldowns: dict[int, float] = {} # {member_id: last_message_timestamp}
        self.pending_updates: dict[tuple[int, int], tuple[int, int]] = {} # {(user_id, guild_id): (time_added, xp_added)}
        self.voice_xp_loop.start()
        self.db_flush_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()
        self.db_flush_loop.cancel()
        if self.pending_updates:
            asyncio.create_task(self.flush_to_db())

    async def cog_load(self):
        # Ensure data directory exists
        self.data_dir = os.getenv('DATA_DIR', 'data')
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, 'leveling.db')
        
        async with aiosqlite.connect(self.db_path) as db:
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
            try:
                await db.execute('ALTER TABLE user_stats ADD COLUMN songs_played INTEGER DEFAULT 0')
            except Exception:
                pass 
            
            # Backfill migration (kept for safety if not run yet)
            await db.execute('''
                UPDATE user_stats 
                SET xp = (total_time / 60) * 10 
                WHERE xp = 0 AND total_time > 0
            ''')
            await db.commit()
        print("Leveling Database Initialized")

    def calculate_level(self, xp: int) -> int:
        return 1 + int(xp / XP_PER_LEVEL)

    async def add_xp(self, user_id: int, guild_id: int, amount: int, db: aiosqlite.Connection) -> bool:
        cursor = await db.execute('SELECT xp, total_time, level FROM user_stats WHERE user_id = ?', (user_id,))
        row = await cursor.fetchone()

        if row:
            current_xp, total_time, current_level = row
            new_xp = current_xp + amount
            new_level = self.calculate_level(new_xp)
            await db.execute('UPDATE user_stats SET xp = ?, level = ? WHERE user_id = ?', (new_xp, new_level, user_id))
            return new_level > current_level
        else:
            new_xp = amount
            new_level = self.calculate_level(new_xp)
            await db.execute('INSERT INTO user_stats (user_id, guild_id, total_time, level, xp, songs_played) VALUES (?, ?, 0, ?, ?, 0)', 
                             (user_id, guild_id, new_level, new_xp))
            return False

    async def flush_to_db(self):
        if not self.pending_updates:
            return

        updates = self.pending_updates.copy()
        self.pending_updates.clear()

        async with aiosqlite.connect(self.db_path) as db:
            # Fetch existing records
            user_ids = [u[0] for u in updates.keys()]
            placeholders = ','.join(['?'] * len(user_ids))
            
            cursor = await db.execute(f'SELECT user_id, guild_id, total_time, xp, level, songs_played FROM user_stats WHERE user_id IN ({placeholders})', user_ids)
            existing_rows = await cursor.fetchall()
            existing_dict = {row[0]: row for row in existing_rows}

            to_update = []
            to_insert = []

            for (user_id, guild_id), (added_time, added_xp) in updates.items():
                if user_id in existing_dict:
                    row = existing_dict[user_id]
                    # row: user_id, guild_id, total_time, xp, level, songs_played
                    new_time = row[2] + added_time
                    new_xp = row[3] + added_xp
                    new_level = self.calculate_level(new_xp)
                    to_update.append((new_time, new_xp, new_level, user_id))
                else:
                    new_level = self.calculate_level(added_xp)
                    to_insert.append((user_id, guild_id, added_time, new_level, added_xp, 0))

            if to_update:
                await db.executemany('UPDATE user_stats SET total_time = ?, xp = ?, level = ? WHERE user_id = ?', to_update)
            if to_insert:
                await db.executemany('INSERT INTO user_stats (user_id, guild_id, total_time, level, xp, songs_played) VALUES (?, ?, ?, ?, ?, ?)', to_insert)
            
            await db.commit()

    async def update_voice_stats_bulk(self, updates: list[tuple[int, int]]):
        """
        updates: list of (user_id, guild_id)
        Added to in-memory cache instead of DB directly to optimize I/O.
        """
        for user_id, guild_id in updates:
            key = (user_id, guild_id)
            if key not in self.pending_updates:
                self.pending_updates[key] = (0, 0)
            
            curr_time, curr_xp = self.pending_updates[key]
            self.pending_updates[key] = (curr_time + VOICE_TIME_PER_TICK, curr_xp + VOICE_XP_PER_TICK)

    async def increment_songs_played(self, user_id: int, guild_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT songs_played FROM user_stats WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            
            if row:
                songs_played = row[0] + 1
                await db.execute('UPDATE user_stats SET songs_played = ? WHERE user_id = ?', (songs_played, user_id))
            else:
                await db.execute('INSERT INTO user_stats (user_id, guild_id, total_time, level, xp, songs_played) VALUES (?, ?, 0, 1, 0, 1)', (user_id, guild_id))
            
            await db.commit()

    @tasks.loop(seconds=5)
    async def voice_xp_loop(self):
        updates: list[tuple[int, int]] = []
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if len(channel.members) == 0:
                    continue
                for member in channel.members:
                    if member.bot:
                        continue
                    if member.voice.self_deaf or member.voice.deaf:
                        pass
                    
                    updates.append((member.id, guild.id))
        
        if updates:
            await self.update_voice_stats_bulk(updates)

    @tasks.loop(minutes=2)
    async def db_flush_loop(self):
        await self.flush_to_db()

    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

    @db_flush_loop.before_loop
    async def before_db_flush_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        user_id = message.author.id
        now = time.time()

        if user_id in self.chat_cooldowns:
            if now - self.chat_cooldowns[user_id] < CHAT_COOLDOWN:
                return

        self.chat_cooldowns[user_id] = now
        
        choice_xp = random.randint(*CHAT_XP_RANGE)
        
        async with aiosqlite.connect(self.db_path) as db:
            await self.add_xp(user_id, message.guild.id, choice_xp, db)
            await db.commit()

    @commands.command(name='level', aliases=['lvl', 'rank'])
    async def level(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT total_time, level, xp FROM user_stats WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if row:
            total_time, level, xp = row
            hours = total_time // 3600
            minutes = (total_time % 3600) // 60
            
            embed = discord.Embed(title=f"{member.name}'s Stats", color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name="Level", value=str(level), inline=True)
            embed.add_field(name="XP", value=f"{xp}", inline=True)
            embed.add_field(name="Total Voice Time", value=f"{hours}h {minutes}m", inline=True)
            
            current_level_floor = (level - 1) * XP_PER_LEVEL
            next_level_xp = level * XP_PER_LEVEL
            
            xp_progress_in_level = xp - current_level_floor
            xp_needed_for_level = next_level_xp - current_level_floor 
            
            percent = min(10, max(0, int((xp_progress_in_level / xp_needed_for_level) * 10)))
            bar = "🟩" * percent + "⬜" * (10 - percent)
            
            percentage_val = int((xp_progress_in_level / xp_needed_for_level) * 100)
            
            embed.add_field(name="Progress to Next Level", value=f"{bar} {percentage_val}%", inline=False)
            
            await ctx.send(embed=embed)
        else:
             await ctx.send(f"❌ {member.name} has no stats recorded yet.")

    async def generate_profile_embed(self, member):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT total_time, level, xp, songs_played FROM user_stats WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if row:
            total_time, level, xp, songs_played = row
        else:
            total_time, level, xp, songs_played = 0, 1, 0, 0

        hours = total_time // 3600
        minutes = (total_time % 3600) // 60
        
        current_level_floor = (level - 1) * XP_PER_LEVEL
        next_level_xp = level * XP_PER_LEVEL
        
        xp_progress_in_level = xp - current_level_floor
        xp_needed_for_level = next_level_xp - current_level_floor
        
        if xp_needed_for_level == 0: xp_needed_for_level = 1
        
        percent = min(10, max(0, int((xp_progress_in_level / xp_needed_for_level) * 10)))
        bar = "🟩" * percent + "⬜" * (10 - percent)
        percentage = int((xp_progress_in_level / xp_needed_for_level) * 100)

        embed = discord.Embed(color=discord.Color.from_str("#FD0061"))
        embed.set_author(name=f"{member.name}'s Profile", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="🎤 Voice Time", value=f"**{hours}h {minutes}m**", inline=True)
        embed.add_field(name="🎵 Songs Played", value=f"**{songs_played}**", inline=True)
        embed.add_field(name="🆙 Level", value=f"**{level}**", inline=True)
        embed.add_field(name="✨ XP", value=f"**{xp}**", inline=True)
        
        embed.add_field(name="XP Progress", value=f"`[{bar}]` **{percentage}%**\n`{xp}/{next_level_xp} XP`", inline=False)
        
        embed.set_footer(text="FEDORA Profile System • Level Up by chatting & talking!", icon_url=self.bot.user.display_avatar.url)
        return embed

    @commands.command(name='xyzprofile', aliases=['pf', 'profile'])
    async def xyzprofile(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = await self.generate_profile_embed(member)
        view = ProfileView(self, member)
        await ctx.send(embed=embed, view=view)

    @commands.command(name='leaderboard', aliases=['lb', 'top'])
    async def leaderboard(self, ctx):
        """Shows the top 10 users by level in the server."""
        guild_id = ctx.guild.id
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('''
                SELECT user_id, level, xp 
                FROM user_stats 
                WHERE guild_id = ? 
                ORDER BY level DESC, xp DESC 
                LIMIT 10
            ''', (guild_id,))
            rows = await cursor.fetchall()
            
        if not rows:
            return await ctx.send("No stats recorded for this server yet.")
            
        embed = discord.Embed(title=f"🏆 {ctx.guild.name} Leaderboard", color=discord.Color.gold())
        
        description = ""
        for i, row in enumerate(rows):
            user_id, level, xp = row
            rank_emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"#{i+1}"
            description += f"{rank_emoji} <@{user_id}> • Level {level} • {xp} XP\n"
            
        embed.description = description
        embed.set_footer(text="Keep chatting & talking to climb the ranks!")
        
        await ctx.send(embed=embed)

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
