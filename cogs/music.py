import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import time
import datetime

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.loops = {} # 0: Off, 1: Current, 2: All
        self.volumes = {} # {guild_id: volume_float}
        self.current_song = {} # {guild_id: song_entry}
        self.last_np_msg = {} # {guild_id: message}
        self.start_times = {} # {guild_id: time.time()}
        self.pause_starts = {} # {guild_id: time.time()}
        self.yt_dlp_options = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': False, # Enable playlists
            'extract_flat': 'in_playlist', # Fast extraction for playlists
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
        }
        
        # Check for cookies.txt
        if os.path.exists('cookies.txt'):
            self.yt_dlp_options['cookiefile'] = 'cookies.txt'
            print("🍪 Loaded cookies.txt for authentication")
        else:
            print("⚠️ cookies.txt not found. YouTube may restrict playback.")

        self.ffmpeg_options = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }
        self.ytdl = yt_dlp.YoutubeDL(self.yt_dlp_options)
        
        # Spotify Init
        client_id = os.getenv('SPOTIPY_CLIENT_ID')
        client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
        if client_id and client_secret:
            self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))
        else:
            self.sp = None
            print("Spotify credentials not found. Spotify support disabled.")

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
        title = entry.get('title', 'Unknown Title')
        
        # Extract info (Full Extraction if it was flat)
        loop = asyncio.get_event_loop()
        try:
            # Re-extract info using the URL (id-based URL preferred from flat extraction)
            data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(url, download=False))
            
            if 'entries' in data:
                data = data['entries'][0]
                
            filename = data['url']
            title = data.get('title', title) # Update title if we have better one
            
            # Update entry with full data for potential looping (and now playing info)
            entry['title'] = title
            entry['duration'] = data.get('duration')
            entry['thumbnail'] = data.get('thumbnail')
            # entry['url'] = data['webpage_url'] # Keep original URL for re-extraction or use stream url? 
            # If we reuse entry for loop, we want the persistent URL, not the stream URL (filename).
            # So typically we keep 'url' as the webpage/id url.
            
            self.current_song[guild_id] = entry # Update current song
            self.start_times[guild_id] = time.time()
            if guild_id in self.pause_starts:
                del self.pause_starts[guild_id]
            
            source = discord.FFmpegPCMAudio(filename, **self.ffmpeg_options)
            source = discord.PCMVolumeTransformer(source)
            source.volume = self.volumes.get(guild_id, 0.5) # Default to 50%

            
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
                 
                 # Delete previous "Now Playing" message if it exists
                 if guild_id in self.last_np_msg and self.last_np_msg[guild_id]:
                     try:
                        await self.last_np_msg[guild_id].delete()
                     except:
                        pass # Message might already be deleted

                 msg = await ctx.send(f'Now playing: **{title}** {loop_msg}', view=view)
                 self.last_np_msg[guild_id] = msg
            
        except Exception as e:
            print(f"Error processing song: {e}")
            await ctx.send(f"Error playing **{title}**. Skipping...")
            await self.play_next(ctx)

    @commands.command(name='join', aliases=['j'])
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

    @commands.command(name='leave', aliases=['l', 'dc'])
    async def play_leave(self, ctx):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            if ctx.guild.id in self.queues:
                del self.queues[ctx.guild.id]
            if ctx.guild.id in self.current_song:
                del self.current_song[ctx.guild.id]
            if ctx.guild.id in self.loops:
                del self.loops[ctx.guild.id]
            if ctx.guild.id in self.last_np_msg:
                del self.last_np_msg[ctx.guild.id]
            await ctx.send('Left the channel')
        else:
            await ctx.send('I am not in a voice channel!')

    @commands.command(name='loop', aliases=['lp'])
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

    @commands.command(name='play', aliases=['p'])
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
            loop = asyncio.get_event_loop()

            if "spotify.com" in query or "spotify:" in query:
                if not self.sp:
                    await ctx.send("Spotify support is not configured (missing credentials).")
                    return

                await ctx.send("Spotify link detected. Fetching tracks...")
                
                tracks_to_search = []
                
                try:
                    if "track" in query:
                        track = self.sp.track(query)
                        tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                    
                    elif "playlist" in query:
                        results = self.sp.playlist_tracks(query)
                        tracks = results['items']
                        while results['next']:
                            results = self.sp.next(results)
                            tracks.extend(results['items'])
                        
                        for item in tracks:
                            track = item.get('track')
                            if track:
                                tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                                
                    elif "album" in query:
                        results = self.sp.album_tracks(query)
                        tracks = results['items']
                        while results['next']:
                            results = self.sp.next(results)
                            tracks.extend(results['items'])
                        
                        for track in tracks:
                            tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                            
                except Exception as e:
                    await ctx.send(f"Error fetching Spotify data: {e}")
                    return

                if not tracks_to_search:
                     await ctx.send("No tracks found in Spotify link.")
                     return

                await ctx.send(f"Found {len(tracks_to_search)} tracks. Adding to queue...")

                # Optimization: Process first track immediately to start playing, then add rest
                first_query = tracks_to_search[0]
                
                try:
                    data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(f"ytsearch:{first_query}", download=False))
                    if 'entries' in data and data['entries']:
                        track_data = data['entries'][0]
                        entry = {
                            'url': track_data.get('webpage_url'),
                            'title': track_data.get('title', first_query),
                            'requester_id': ctx.author.id
                        }
                        if ctx.guild.id not in self.queues:
                            self.queues[ctx.guild.id] = []
                        self.queues[ctx.guild.id].append(entry)
                        
                        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                            await self.play_next(ctx)
                    else:
                         await ctx.send(f"Could not find **{first_query}** on YouTube.")

                except Exception as e:
                    print(f"Failed to find first track {first_query}: {e}")

                # Process remaining tracks in background
                async def add_remaining_tracks():
                    added_count = 1 
                    for search_query in tracks_to_search[1:]:
                        try:
                            data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(f"ytsearch:{search_query}", download=False))
                            if 'entries' in data and data['entries']:
                                track_data = data['entries'][0]
                                entry = {
                                    'url': track_data.get('webpage_url'),
                                    'title': track_data.get('title', search_query),
                                    'requester_id': ctx.author.id
                                }
                                self.queues[ctx.guild.id].append(entry)
                                added_count += 1
                        except Exception as e:
                            print(f"Failed to find {search_query}: {e}")
                            continue
                            
                    await ctx.send(f"✅ Finished adding all {added_count} Spotify tracks to queue.")

                asyncio.create_task(add_remaining_tracks())
                return

            await ctx.send(f"Searching for **{query}**...")
            data = await loop.run_in_executor(None, lambda: self.ytdl.extract_info(query, download=False))
            
            tracks_to_add = []
            
            if 'entries' in data:
                # Playlist or Search Result
                if data.get('_type') == 'playlist' and not query.startswith('ytsearch'):
                    # It's a proper playlist URL
                    tracks_to_add = data['entries']
                    await ctx.send(f"Found playlist with {len(tracks_to_add)} songs.")
                else:
                    # Search result, just take first
                    tracks_to_add = [data['entries'][0]]
            else:
                # Single Video
                tracks_to_add = [data]

            if not tracks_to_add:
                await ctx.send("No songs found.")
                return

            if ctx.guild.id not in self.queues:
                self.queues[ctx.guild.id] = []
                
            added_count = 0
            for track in tracks_to_add:
                entry = {
                    'url': track.get('original_url') or track.get('webpage_url') or track.get('url'),
                    'title': track.get('title', 'Unknown Title'),
                    'requester_id': ctx.author.id
                }
                self.queues[ctx.guild.id].append(entry)
                added_count += 1
            
            if added_count == 1:
                await ctx.send(f"Added to queue: **{tracks_to_add[0].get('title')}**")
            else:
                await ctx.send(f"Added **{added_count}** songs to queue.")

            # If not playing, start playing
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await self.play_next(ctx)
                
        except Exception as e:
            print(f"Play error: {e}")
            await ctx.send("An error occurred while searching/playing. Make sure it's a valid link or search term.")

    @commands.command(name='pause', aliases=['ps'])
    async def pause(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            self.pause_starts[ctx.guild.id] = time.time()
            await ctx.send("Paused ⏸️")

    @commands.command(name='resume', aliases=['res'])
    async def resume(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            if ctx.guild.id in self.pause_starts:
                paused_duration = time.time() - self.pause_starts[ctx.guild.id]
                if ctx.guild.id in self.start_times:
                    self.start_times[ctx.guild.id] += paused_duration
                del self.pause_starts[ctx.guild.id]
            await ctx.send("Resumed ▶️")

    @commands.command(name='stop', aliases=['st'])
    async def stop(self, ctx):
        if ctx.voice_client:
            ctx.voice_client.stop()
            self.queues[ctx.guild.id] = []
            self.current_song[ctx.guild.id] = None
            self.loops[ctx.guild.id] = 0
            
            # Clean up the last "Now playing" message reference, but maybe not delete it on stop?
            # Or should we? The user asked for "when next song plays".
            # I'll just clear the reference so we don't try to delete an old one next time we restart.
            if ctx.guild.id in self.last_np_msg:
                del self.last_np_msg[ctx.guild.id]

            await ctx.send("Stopped and cleared queue.")

    @commands.command(name='queue', aliases=['q'])
    async def queue(self, ctx):
        if ctx.guild.id in self.queues and self.queues[ctx.guild.id]:
            queue_list = self.queues[ctx.guild.id]
            
            # Use Pagination View
            view = QueuePaginationView(ctx, queue_list)
            embed = view.get_embed()
            view.update_buttons()
            
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send("Queue is empty.")

    @commands.command(name='skip', aliases=['s', 'next'])
    async def skip(self, ctx, index: int = None):
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            return await ctx.send("Nothing is playing.")

        if index is not None:
            if ctx.guild.id not in self.queues or not self.queues[ctx.guild.id]:
                return await ctx.send("Queue is empty, cannot skip to specific index.")
            
            if index < 1 or index > len(self.queues[ctx.guild.id]):
                 return await ctx.send(f"Invalid index. Please provide a number between 1 and {len(self.queues[ctx.guild.id])}.")
            
            # Skip to specific index (Move to Top):
            # We want to play the song at index (1-based) next.
            # So we move it to index 0, pushing everything else down.
            # e.g. Queue: [A, B, C, D]. !skip 3 (Target C).
            # Pop C. Queue: [A, B, D].
            # Insert C at 0. Queue: [C, A, B, D].
            # Then stop() triggers play_next(), which plays C.
            
            target_song = self.queues[ctx.guild.id].pop(index-1)
            self.queues[ctx.guild.id].insert(0, target_song)
            
            await ctx.send(f"⏭️ Jumping to **{target_song['title']}** (moved to top of queue).")
            ctx.voice_client.stop()
        else:
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skipped song.")

    @commands.command(name='volume', aliases=['v', 'vol'])
    async def volume(self, ctx, volume: int):
        """Sets the volume of the player (0-100)"""
        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")

        if volume < 0 or volume > 100:
            return await ctx.send("Volume must be between 0 and 100.")

        self.volumes[ctx.guild.id] = volume / 100
        
        if ctx.voice_client.source:
            if hasattr(ctx.voice_client.source, 'volume'):
                ctx.voice_client.source.volume = volume / 100
        
        await ctx.send(f"🔊 Volume set to **{volume}%**")

    @commands.command(name='nowplaying', aliases=['np', 'current'])
    async def now_playing(self, ctx):
        """Shows the currently playing song with progress bar"""
        guild_id = ctx.guild.id
        
        if guild_id not in self.current_song or not self.current_song[guild_id]:
            return await ctx.send("Nothing is currently playing.")
            
        entry = self.current_song[guild_id]
        
        # Calculate progress
        current_time = 0
        if guild_id in self.start_times:
            if guild_id in self.pause_starts:
                 # If currently paused, use time up to pause
                 current_time = self.pause_starts[guild_id] - self.start_times[guild_id]
            else:
                 current_time = time.time() - self.start_times[guild_id]
        
        duration = entry.get('duration', 0)
        
        # Create Bar
        # [▬▬▬▬▬▬▬▬▬🔘▬▬▬▬▬▬▬▬]
        bar_length = 20
        if duration > 0:
            progress = min(current_time / duration, 1.0)
            filled_len = int(progress * bar_length)
            bar = "▬" * filled_len + "🔘" + "▬" * (bar_length - filled_len)
            
            # Identify timestamps
            current_str = str(datetime.timedelta(seconds=int(current_time)))
            total_str = str(datetime.timedelta(seconds=int(duration)))
            time_str = f"{current_str} / {total_str}"
        else:
            bar = "🔘" + "▬" * bar_length
            current_str = str(datetime.timedelta(seconds=int(current_time)))
            time_str = f"{current_str} / Live"
            
        embed = discord.Embed(title="Now Playing 🎵", description=f"[{entry['title']}]({entry.get('url', '')})", color=discord.Color.blue())
        
        if entry.get('thumbnail'):
            embed.set_thumbnail(url=entry['thumbnail'])
            
        embed.add_field(name="Progress", value=f"`{time_str}`\n`{bar}`", inline=False)
        
        requester = ctx.guild.get_member(entry.get('requester_id'))
        req_name = requester.display_name if requester else "Unknown"
        embed.set_footer(text=f"Requested by {req_name}", icon_url=requester.display_avatar.url if requester else None)
        
        await ctx.send(embed=embed)

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
            queue_list = self.cog.queues[self.ctx.guild.id]
            max_lines = 10
            queue_str = "\n".join([f"{i+1}. {entry['title']}" for i, entry in enumerate(queue_list[:max_lines])])
            if len(queue_list) > max_lines:
                queue_str += f"\n... and {len(queue_list) - max_lines} more."
            await interaction.response.send_message(f"**Current Queue ({len(queue_list)} songs):**\n{queue_str}", ephemeral=True)
        else:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Music(bot))

class QueuePaginationView(discord.ui.View):
    def __init__(self, ctx, queue_list):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.queue_list = queue_list
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(queue_list) - 1) // self.items_per_page + 1

    def update_buttons(self):
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == self.total_pages - 1

    def get_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_items = self.queue_list[start:end]
        
        queue_str = "\n".join([f"{start + i + 1}. {entry['title']}" for i, entry in enumerate(current_items)])
        
        embed = discord.Embed(title=f"Current Queue ({len(self.queue_list)} songs)", description=queue_str, color=discord.Color.blue())
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()
            
    async def on_timeout(self):
        # Optional: Disable buttons on timeout
        for child in self.children:
            child.disabled = True
        # Note: We can't edit the message easily without reference, 
        # but interaction.message is available in button callbacks.
        # Here we usually just pass.
        pass
