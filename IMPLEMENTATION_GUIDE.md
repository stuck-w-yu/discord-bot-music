# Panduan Implementasi Optimasi ke musik.py

Dokumen ini menunjukkan langkah-langkah praktis untuk mengintegrasikan modul optimasi ke dalam file musik.py yang sudah ada.

## Langkah 1: Update Import

**Sebelum** (existing imports):
```python
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import time
import datetime
import json
```

**Sesudah** (dengan optimasi):
```python
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import time
import datetime
import json

# Import optimization modules
from .guild_state import GuildStateManager, GuildState
from .extract_cache import ExtractInfoCache
from .perf_config import OptimizedFFmpegOptions, OptimizedYtdlpOptions, BotPerformanceConfig
```

---

## Langkah 2: Update Music Class __init__

**Sebelum** (multiple dictionaries):
```python
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.queues: Dict[int, List[Dict[str, Any]]] = {}
        self.loops: Dict[int, int] = {}
        self.volumes: Dict[int, float] = {}
        self.current_song: Dict[int, Optional[Dict[str, Any]]] = {}
        self.last_np_msg: Dict[int, Optional[discord.Message]] = {}
        self.last_channel: Dict[int, int] = {}
        self.start_times: Dict[int, float] = {}
        self.pause_starts: Dict[int, float] = {}
        self.pause_votes: Dict[int, Set[int]] = {}
        self.skip_votes: Dict[int, Set[int]] = {}
        self.stop_votes: Dict[int, Set[int]] = {}
        
        # ... more code ...
```

**Sesudah** (dengan optimization):
```python
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        
        # Use unified state manager instead of multiple dictionaries
        self.state_manager = GuildStateManager()
        
        # Load performance configuration
        self.config = BotPerformanceConfig()
        
        # Initialize extraction cache
        self.extract_cache = ExtractInfoCache(
            max_size=self.config.EXTRACT_CACHE_MAX_SIZE,
            ttl_seconds=self.config.EXTRACT_CACHE_TTL_SECONDS
        )
        
        # Use optimized FFmpeg options
        self.ffmpeg_options = OptimizedFFmpegOptions.get('standard')
        
        # Use optimized yt-dlp options
        yt_dlp_opts = OptimizedYtdlpOptions.get('fast')
        
        # Add cookie support if available
        data_dir = os.getenv('DATA_DIR', 'data')
        data_cookie_path = os.path.join(data_dir, 'cookies.txt')
        if os.path.exists(data_cookie_path):
            yt_dlp_opts['cookiefile'] = data_cookie_path
        
        self.ytdl = yt_dlp.YoutubeDL(yt_dlp_opts)
        
        # Queue file (jika menggunakan persistence)
        self.queue_file = os.path.join(data_dir, 'queues.json')
        
        # Spotify initialization (jika tersedia)
        client_id = os.getenv('SPOTIPY_CLIENT_ID')
        client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
        if client_id and client_secret:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret
                )
            )
        else:
            self.sp = None
            print("⚠️ Spotify credentials not found")
        
        # Start cleanup task
        self.bot.loop.create_task(self._periodic_cleanup())
```

---

## Langkah 3: Update Command Methods - Contoh play_leave

**Sebelum**:
```python
@commands.command(name='leave', aliases=['l', 'dc'])
async def play_leave(self, ctx: commands.Context) -> None:
    if ctx.voice_client:
        await ctx.voice_client.disconnect(force=True)
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
```

**Sesudah** (dengan optimization):
```python
@commands.command(name='leave', aliases=['l', 'dc'])
@ensure_voice()
async def play_leave(self, ctx: commands.Context) -> None:
    if ctx.voice_client:
        await ctx.voice_client.disconnect(force=True)
        # Clean up all state in one operation
        await self.state_manager.cleanup_guild(ctx.guild.id)
        await ctx.send('Left the channel')
    else:
        await ctx.send('I am not in a voice channel!')
```

---

## Langkah 4: Update play_next_internal Method

**Sebelum** (menggunakan multiple dictionaries):
```python
async def play_next_internal(self, guild_id: int, vc, ctx=None):
    if not vc: return
    
    loops = self.loops.get(guild_id, 0)
    previous_song = self.current_song.get(guild_id)
    
    entry = None
    if loops == 1 and previous_song:
        entry = previous_song
    elif loops == 2 and previous_song:
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        self.queues[guild_id].append(previous_song)
    
    if not entry:
        if guild_id in self.queues and self.queues[guild_id]:
            entry = self.queues[guild_id].pop(0)
        else:
            self.current_song[guild_id] = None
            return
    
    # ... extract and play ...
    
    self.start_times[guild_id] = time.time()
    if guild_id in self.pause_starts:
        del self.pause_starts[guild_id]
    self.pause_votes[guild_id] = set()
    self.skip_votes[guild_id] = set()
    self.stop_votes[guild_id] = set()
```

**Sesudah** (dengan optimization):
```python
async def play_next_internal(self, guild_id: int, vc, ctx=None) -> None:
    if not vc:
        return
    
    # Get guild state (creates if doesn't exist)
    state = self.state_manager.get_or_create(guild_id)
    
    # Handle loop modes
    entry = None
    if state.loop_mode == 1 and state.current_song:
        # Loop current song
        entry = state.current_song
    elif state.loop_mode == 2 and state.current_song:
        # Loop queue - add current back to queue
        state.queue.append(state.current_song)
    
    # Get next song from queue if no entry
    if not entry:
        if state.queue:
            entry = state.queue.pop(0)
        else:
            state.current_song = None
            return
    
    # Check queue size limits
    if len(state.queue) >= self.config.MAX_QUEUE_SIZE:
        print(f"⚠️ Guild {guild_id} queue at max size: {len(state.queue)}")
    
    title = entry.get('title', 'Unknown Title')
    
    try:
        # Get stream URL with cache support
        stream_url = await self._get_stream_url_cached(entry)
        if not stream_url:
            await self.play_next_internal(guild_id, vc, ctx)
            return
        
        # Update state
        state.current_song = entry
        state.start_time = time.time()
        state.clear_pause_state()
        state.reset_votes()
        
        # Create audio source
        source = discord.FFmpegPCMAudio(
            stream_url,
            before_options=self.ffmpeg_options['before_options'],
            options=self.ffmpeg_options['options'],
        )
        source = discord.PCMVolumeTransformer(source)
        source.volume = state.volume
        
        # Play audio
        if vc and vc.is_connected():
            vc.play(source, after=self._make_after_play(guild_id, vc, ctx))
            
            # Send now-playing message
            if ctx or state.last_channel_id:
                channel = ctx.channel if ctx else self.bot.get_channel(state.last_channel_id)
                if channel and isinstance(channel, discord.abc.Messageable):
                    await state.cleanup_message()  # Remove old message
                    
                    loop_msg = ""
                    if state.loop_mode == 1:
                        loop_msg = " 🔂 [Loop Current]"
                    elif state.loop_mode == 2:
                        loop_msg = " 🔁 [Loop Queue]"
                    
                    msg = await channel.send(f'🎵 Now playing: **{title}**{loop_msg}')
                    state.last_np_msg = msg
                    state.last_channel_id = channel.id
    
    except Exception as e:
        print(f"❌ Error playing song: {e}")
        if ctx:
            await ctx.send(f"❌ Error playing **{title}**. Skipping...")
        await self.play_next_internal(guild_id, vc, ctx)
```

---

## Langkah 5: Add Helper Method untuk Cache

**Tambahkan method ini ke Music class**:

```python
async def _get_stream_url_cached(self, entry: Dict[str, Any]) -> Optional[str]:
    """Get stream URL with caching support."""
    url = entry.get('url')
    if isinstance(url, str) and url.strip():
        return url
    
    # Try to refresh URL (untuk expired URLs)
    original_url = entry.get('original_url') or entry.get('webpage_url')
    if original_url:
        # Check cache first
        cached = self.extract_cache.get(original_url)
        if cached and 'url' in cached:
            return cached['url']
        
        # Extract with timeout
        try:
            data = await asyncio.wait_for(
                self._extract_info_async(original_url),
                timeout=self.config.EXTRACTION_TIMEOUT_SECONDS
            )
            if data and 'url' in data:
                self.extract_cache.set(original_url, data)
                return data['url']
        except asyncio.TimeoutError:
            print(f"⏱️ Extraction timeout for {original_url}")
        except Exception as e:
            print(f"⚠️ Extraction error: {e}")
    
    return entry.get('stream_url')
```

---

## Langkah 6: Add Periodic Cleanup Task

**Tambahkan method ini ke Music class**:

```python
async def _periodic_cleanup(self) -> None:
    """Periodically clean up expired cache entries dan inactive guild states."""
    await self.bot.wait_until_ready()
    
    while not self.bot.is_closed():
        try:
            # Clean up expired cache entries
            self.extract_cache.cleanup_expired()
            
            # Clean up inactive guild states (after 1 hour)
            current_time = time.time()
            inactive_guilds = []
            for guild_id, state in self.state_manager.states.items():
                if not state.current_song and not state.queue:
                    if state.start_time + self.config.CLEANUP_EMPTY_GUILD_STATE_AFTER_SECONDS < current_time:
                        inactive_guilds.append(guild_id)
            
            for guild_id in inactive_guilds:
                self.state_manager.remove(guild_id)
            
            if inactive_guilds:
                print(f"🧹 Cleaned up {len(inactive_guilds)} inactive guild states")
            
            # Wait 5 minutes before next cleanup
            await asyncio.sleep(300)
        
        except Exception as e:
            print(f"❌ Cleanup task error: {e}")
            await asyncio.sleep(60)
```

---

## Langkah 7: Update Loop Command

**Sebelum**:
```python
@commands.command(name='loop', aliases=['lp'])
async def loop(self, ctx, mode=None):
    current_state = self.loops.get(ctx.guild.id, 0)
    # ... logic ...
    self.loops[ctx.guild.id] = new_state
```

**Sesudah**:
```python
@commands.command(name='loop', aliases=['lp'])
@ensure_voice()
async def loop(self, ctx: commands.Context, mode: Optional[str] = None) -> None:
    state = self.state_manager.get_or_create(ctx.guild.id)
    current_state = state.loop_mode
    
    if mode:
        mode = mode.lower()
        if mode == 'all':
            new_state = 2
        elif mode in ['current', 'song', 'one']:
            new_state = 1
        elif mode in ['off', 'none', 'disable']:
            new_state = 0
        else:
            return await ctx.send("❌ Invalid loop mode. Use `all`, `current`, or `off`.")
    else:
        new_state = (current_state + 1) % 3
    
    state.loop_mode = new_state
    
    msg = "Loop disabled ➡️"
    if new_state == 1:
        msg = "🔂 Looping **Current Song**"
    elif new_state == 2:
        msg = "🔁 Looping **Queue**"
    
    await ctx.send(msg)
```

---

## Quick Migration Checklist

- [ ] Backup original `cogs/music.py`
- [ ] Add new optimization imports
- [ ] Replace __init__ method
- [ ] Update play_leave command
- [ ] Update play_next_internal method
- [ ] Add _get_stream_url_cached helper
- [ ] Add _periodic_cleanup task
- [ ] Update loop command
- [ ] Test basic playback
- [ ] Test cache by playing same song twice
- [ ] Verify cleanup with !leave command
- [ ] Monitor memory usage

---

## Testing Tips

```python
# In a test command or event handler:

@commands.command(name='debug')
async def debug_info(self, ctx):
    state = self.state_manager.get(ctx.guild.id)
    if state:
        cache_stats = self.extract_cache.get_stats()
        msg = f"""
**Debug Info:**
- Queue size: {len(state.queue)}
- Current song: {state.current_song.get('title') if state.current_song else 'None'}
- Volume: {state.volume}
- Loop mode: {state.loop_mode}
- Cache size: {cache_stats['size']}/{cache_stats['max_size']}
        """
        await ctx.send(msg)
```

---

**Good luck dengan implementasi optimasi! 🎵**
