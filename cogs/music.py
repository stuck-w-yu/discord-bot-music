import discord
from discord.ext import commands
import yt_dlp
import asyncio

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.loops = {} # 0: Off, 1: Current, 2: All
        self.current_song = {} # {guild_id: song_entry}
        self.yt_dlp_options = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
        }
        self.ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }
        self.ytdl = yt_dlp.YoutubeDL(self.yt_dlp_options)

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        loops = self.loops.get(guild_id, 0)
        previous_song = self.current_song.get(guild_id)
        
        # Logic to determine next song
        entry = None
        
        # If Loop Current (1) and we have a previous song, replay it
        if loops == 1 and previous_song:
            entry = previous_song
            
        # If Loop All (2) and we have a previous song, re-queue it
        elif loops == 2 and previous_song:
            if guild_id not in self.queues:
                self.queues[guild_id] = []
            self.queues[guild_id].append(previous_song)
            
        # If entry is still None (Loop Off or Loop All processed), get from queue
        if not entry:
            if guild_id in self.queues and self.queues[guild_id]:
                entry = self.queues[guild_id].pop(0)
            else:
                # Queue empty
                self.current_song[guild_id] = None
                return

        # Play the entry
        url = entry['url']
        requester_id = entry.get('requester_id')
        self.current_song[guild_id] = entry # Update current song
        
        # Extract info
        loop = asyncio.get_event_loop()
        try:
            # Re-extract info because URLs might expire
            # Note: For youtube, url might expire, best to re-extract or store id and reconstruct?
            # Current implementation stores webpage_url, which is persistent. 
            data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            
            if 'entries' in data:
                data = data['entries'][0]
                
            filename = data['url']
            title = data['title']
            
            source = discord.FFmpegPCMAudio(filename, **self.ffmpeg_options)
            
            if ctx.voice_client and ctx.voice_client.is_connected():
                 # Increment songs played for the requester
                 if requester_id:
                     leveling_cog = self.bot.get_cog('Leveling')
                     if leveling_cog:
                         await leveling_cog.increment_songs_played(requester_id, ctx.guild.id)

                 ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
                 view = MusicPlayerView(self, ctx)
                 
                 # Add loop status to now playing
                 loop_msg = ""
                 if loops == 1: loop_msg = "🔂 Loop Current"
                 elif loops == 2: loop_msg = "🔁 Loop All"
                 
                 await ctx.send(f'Now playing: **{title}** {loop_msg}', view=view)
            
        except Exception as e:
            print(f"Error processing song: {e}")
            await ctx.send("An error occurred while trying to play the song. Playing next...")
            await self.play_next(ctx)

    @commands.command(name='join')
    async def play_join(self, ctx):
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            if ctx.voice_client:
                await ctx.voice_client.move_to(channel)
            else:
                await channel.connect()
            await ctx.send(f'Joined {channel}')
        else:
            await ctx.send('You are not in a voice channel!')

    @commands.command(name='leave')
    async def play_leave(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            if ctx.guild.id in self.queues:
                del self.queues[ctx.guild.id]
            if ctx.guild.id in self.current_song:
                del self.current_song[ctx.guild.id]
            if ctx.guild.id in self.loops:
                del self.loops[ctx.guild.id]
            await ctx.send('Left the channel')
        else:
            await ctx.send('I am not in a voice channel!')

    @commands.command(name='loop')
    async def loop(self, ctx):
        """Cycles loop mode: Off -> Current -> All -> Off"""
        current_state = self.loops.get(ctx.guild.id, 0)
        new_state = (current_state + 1) % 3
        self.loops[ctx.guild.id] = new_state
        
        msg = "Loop disabled ➡️"
        if new_state == 1:
            msg = "Looping **Current Song** 🔂"
        elif new_state == 2:
            msg = "Looping **Queue** 🔁"
            
        await ctx.send(msg)

    @commands.command(name='play')
    async def play(self, ctx, *, query):
        if not ctx.voice_client:
            try:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect()
                else:
                    await ctx.send("You are not in a voice channel!")
                    return
            except Exception as e:
                await ctx.send(f"Could not join channel: {e}")
                return
            
        try:
            if "spotify.com" in query:
                 await ctx.send("Spotify link detected. Searching on YouTube...")
                 pass

            await ctx.send(f"Searching for **{query}**...")
            
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(query, download=False))

            if 'entries' in data:
                data = data['entries'][0]
            
            if ctx.guild.id not in self.queues:
                self.queues[ctx.guild.id] = []
                
            entry = {'url': data['webpage_url'], 'title': data['title'], 'requester_id': ctx.author.id}

            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                # Play immediately
                filename = data['url']
                title = data['title']
                
                # Update current song immediately
                self.current_song[ctx.guild.id] = entry
                
                source = discord.FFmpegPCMAudio(filename, **self.ffmpeg_options)
                
                leveling_cog = self.bot.get_cog('Leveling')
                if leveling_cog:
                     await leveling_cog.increment_songs_played(ctx.author.id, ctx.guild.id)

                ctx.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self.play_next(ctx), self.bot.loop))
                view = MusicPlayerView(self, ctx)
                
                loops = self.loops.get(ctx.guild.id, 0)
                loop_msg = ""
                if loops == 1: loop_msg = "🔂"
                elif loops == 2: loop_msg = "🔁"
                 
                await ctx.send(f'Now playing: **{title}** {loop_msg}', view=view)
            else:
                # Add to queue
                self.queues[ctx.guild.id].append(entry)
                await ctx.send(f'Added to queue: **{data["title"]}**')
                
        except Exception as e:
            print(f"Play error: {e}")
            await ctx.send("An error occurred while searching/playing. Make sure it's a valid link or search term.")

    @commands.command(name='pause')
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("Paused ⏸️")

    @commands.command(name='resume')
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("Resumed ▶️")

    @commands.command(name='stop')
    async def stop(self, ctx):
        if ctx.voice_client:
            ctx.voice_client.stop()
            self.queues[ctx.guild.id] = []
            self.current_song[ctx.guild.id] = None
            self.loops[ctx.guild.id] = 0
            await ctx.send("Stopped and cleared queue.")

    @commands.command(name='queue')
    async def queue(self, ctx):
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            queue_str = "\n".join([f"{i+1}. {entry['title']}" for i, entry in enumerate(self.queues[ctx.guild.id])])
            await ctx.send(f"Current Queue:\n{queue_str}")
        else:
            await ctx.send("Queue is empty.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skipped song.")
        else:
            await ctx.send("Nothing to skip.")

class MusicPlayerView(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="music_pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
             await interaction.response.send_message("Nothing is playing!", ephemeral=True)
             return
        
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed", ephemeral=True)
        else:
            vc.pause()
            await interaction.response.send_message("⏸️ Paused", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing to skip", ephemeral=True)

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.success, custom_id="music_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Toggle Loop
        current_state = self.cog.loops.get(self.ctx.guild.id, 0)
        new_state = (current_state + 1) % 3
        self.cog.loops[self.ctx.guild.id] = new_state
        
        msg = "Loop disabled ➡️"
        if new_state == 1:
            msg = "Looping **Current Song** 🔂"
        elif new_state == 2:
            msg = "Looping **Queue** 🔁"
            
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.guild.voice_client
        if vc:
            vc.stop()
            self.cog.queues[self.ctx.guild.id] = []
            self.cog.current_song[self.ctx.guild.id] = None
            self.cog.loops[self.ctx.guild.id] = 0
            await interaction.response.send_message("⏹️ Stopped and queue cleared", ephemeral=True)
        else:
            await interaction.response.send_message("Not connected", ephemeral=True)

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="music_queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.ctx.guild.id in self.cog.queues and self.cog.queues[self.ctx.guild.id]:
            queue_str = "\n".join([f"{i+1}. {entry['title']}" for i, entry in enumerate(self.cog.queues[self.ctx.guild.id])])
            await interaction.response.send_message(f"**Current Queue:**\n{queue_str}", ephemeral=True)
        else:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Music(bot))
