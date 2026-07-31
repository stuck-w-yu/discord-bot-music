# pyright: reportGeneralTypeIssues=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportAttributeAccessIssue=false, reportReturnType=false
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
import re
import base64
from typing import Optional, Dict, List, Any, Set, cast, Union

from cogs.extract_cache import ExtractInfoCache
from cogs.guild_state import GuildStateManager, GuildState
from cogs.perf_config import OptimizedFFmpegOptions
from cogs.utils import (
    ensure_voice,
    spotify_track_url_from_query,
    spotify_resource_id_from_query,
    spotify_public_track_query,
    spotify_public_collection_queries,
    spotify_public_queries,
    extract_info_with_ytdl
)

# Hardcoded tuning for busy servers (adjust in code if needed).
SEARCH_RESOLVE_MAX_RETRIES = 5
SEARCH_RESOLVE_RETRY_DELAY_SEC = 3.0
YTDLP_CONCURRENCY = 1


def _votes_needed(vc: discord.VoiceProtocol) -> int:
    """Dynamic vote threshold based on non-bot members in the voice channel."""
    channel = getattr(vc, 'channel', None)
    if channel is None or not hasattr(channel, 'members'):
        return 1
    non_bot_members = [m for m in channel.members if not m.bot]
    member_count = len(non_bot_members)
    if member_count <= 1:
        return 1
    if member_count <= 4:
        return 2
    return 3



def _make_vote_embed(
    action: str,
    current_votes: int,
    votes_needed: int,
    voter: Union[discord.Member, discord.User],
) -> discord.Embed:
    """Return an embed showing vote progress for pause/skip/stop actions."""
    action_emoji = {"pause": "⏸️", "skip": "⏭️", "stop": "⏹️"}.get(action, "🗳️")
    bar = "█" * current_votes + "░" * (votes_needed - current_votes)
    remaining = votes_needed - current_votes
    embed = discord.Embed(
        title=f"🗳️ Vote to {action.capitalize()}",
        description=f"{action_emoji} **{action.capitalize()}** vote registered!",
        color=discord.Color.orange(),
    )
    embed.add_field(
        name="Progress",
        value=f"`{bar}` **{current_votes}/{votes_needed}**",
        inline=False,
    )
    embed.add_field(name="Voted by", value=voter.mention, inline=True)
    embed.set_footer(text=f"Need {remaining} more vote(s) to {action}")
    return embed
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.states = GuildStateManager()
        self.cache = ExtractInfoCache(max_size=100)
        self._save_queues_task: Optional[asyncio.Task[None]] = None
        # Throttle/batch noisy playback error chat messages.
        self._playback_error_buffers: Dict[int, List[str]] = {}
        self._playback_error_flush_tasks: Dict[int, asyncio.Task[None]] = {}
        self._ytdlp_sema = asyncio.Semaphore(max(1, YTDLP_CONCURRENCY))
        self.youtube_auth_ready: bool = False
        self.yt_dlp_options: Dict[str, Any] = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': False, # Enable playlists
            'extract_flat': False, # Changed to False to get REAL streaming URLs on first pass
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0',
            # More time for resolving/searching when many requests arrive at once.
            'socket_timeout': 30,
            'retries': 3,
            'fragment_retries': 3,
        }
        
        # Check for cookies
        data_dir = os.getenv('DATA_DIR', 'data')
        self.queue_file = os.path.join(data_dir, 'queues.json')
        data_cookie_path = os.path.join(data_dir, 'cookies.txt')
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        local_data_cookie_path = os.path.join(project_root, 'data', 'cookies.txt')
        local_root_cookie_path = os.path.join(project_root, 'cookies.txt')

        cookie_file_env = (
            os.getenv('YOUTUBE_COOKIES_FILE')
            or os.getenv('COOKIE_FILE')
            or os.getenv('YTDLP_COOKIEFILE')
        )
        youtube_cookies = os.getenv('YOUTUBE_COOKIES', '')
        resolved_cookie_file: Optional[str] = None

        # File-first behavior: prefer existing cookie file in DATA_DIR or project root.
        if os.path.exists(data_cookie_path):
            self.yt_dlp_options['cookiefile'] = data_cookie_path
            self.youtube_auth_ready = True
            print(f"🍪 Loaded {data_cookie_path} for authentication")
        elif os.path.exists(local_data_cookie_path):
            self.yt_dlp_options['cookiefile'] = local_data_cookie_path
            self.youtube_auth_ready = True
            print(f"🍪 Loaded {local_data_cookie_path} for authentication")
        elif os.path.exists('cookies.txt'):
            self.yt_dlp_options['cookiefile'] = 'cookies.txt'
            self.youtube_auth_ready = True
            print("🍪 Loaded local cookies.txt for authentication")
        elif os.path.exists(local_root_cookie_path):
            self.yt_dlp_options['cookiefile'] = local_root_cookie_path
            self.youtube_auth_ready = True
            print(f"🍪 Loaded {local_root_cookie_path} for authentication")
        elif cookie_file_env and os.path.exists(cookie_file_env):
            resolved_cookie_file = cookie_file_env
            self.yt_dlp_options['cookiefile'] = resolved_cookie_file
            self.youtube_auth_ready = True
            print(f"🍪 Loaded cookie file from env path: {cookie_file_env}")
        elif youtube_cookies and os.path.exists(youtube_cookies):
            resolved_cookie_file = youtube_cookies
            self.yt_dlp_options['cookiefile'] = resolved_cookie_file
            self.youtube_auth_ready = True
            print(f"🍪 Loaded cookie file from YOUTUBE_COOKIES path: {youtube_cookies}")
        elif youtube_cookies:
            os.makedirs(data_dir, exist_ok=True)
            cookie_text = youtube_cookies

            # Handle escaped newline format from .env single-line values.
            if "\\n" in cookie_text:
                cookie_text = cookie_text.replace("\\n", "\n")

            # Optional base64 format: YOUTUBE_COOKIES=base64:<encoded_content>
            if cookie_text.startswith('base64:'):
                try:
                    encoded = cookie_text.split(':', 1)[1].strip()
                    cookie_text = base64.b64decode(encoded).decode('utf-8', errors='ignore')
                except Exception as e:
                    print(f"⚠️ Failed to decode base64 cookies from env: {e}")
                    cookie_text = ''

            if cookie_text:
                cookie_write_targets = [data_cookie_path, local_data_cookie_path]
                for target_path in cookie_write_targets:
                    try:
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with open(target_path, 'w') as f:
                            f.write(cookie_text)
                        self.yt_dlp_options['cookiefile'] = target_path
                        self.youtube_auth_ready = True
                        print(f"🍪 Created {target_path} from environment variable content")
                        break
                    except Exception as write_error:
                        print(f"⚠️ Failed writing cookies to {target_path}: {write_error}")
        else:
            print("⚠️ cookies.txt not found. YouTube may restrict playback.")
            checked_paths = [
                data_cookie_path,
                local_data_cookie_path,
                os.path.abspath('cookies.txt'),
                local_root_cookie_path,
                cookie_file_env or '(env path not set)',
            ]
            print(f"Cookie lookup cwd: {os.getcwd()}")
            print("Cookie paths checked:")
            for p in checked_paths:
                print(f" - {p}")

        self.ffmpeg_options = OptimizedFFmpegOptions.get('standard')
        self.ytdl = yt_dlp.YoutubeDL(self.yt_dlp_options)
        
        # Spotify Init
        client_id = os.getenv('SPOTIPY_CLIENT_ID')
        client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
        if client_id and client_secret:
            self.sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))
        else:
            self.sp = None
            print("Spotify credentials not found. Spotify support disabled.")

        # Ensure data directory exists for queue persistence
        if self.queue_file:
            os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
            
        # Load persistent queues
        self.load_queues()

    async def _delete_last_status_message(self, guild_id: int) -> None:
        state = self.states.get(guild_id)
        if not state or not state.last_channel_id or not state.last_status_msg_id:
            return

        channel = self.bot.get_channel(state.last_channel_id)
        if channel and isinstance(channel, discord.abc.Messageable):
            try:
                msg = await channel.fetch_message(state.last_status_msg_id)
                # Don't delete the now-playing message.
                if state.last_np_msg_id and msg.id == state.last_np_msg_id:
                    return
                await msg.delete()
            except Exception:
                pass
        state.last_status_msg_id = None

    async def _send_status(
        self,
        ctx: commands.Context,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        view: Optional[discord.ui.View] = None,
    ) -> discord.Message:
        """Send a single 'status' message per guild to avoid chat spam.

        Deletes the previous status message (if any) but keeps the 'Now playing' message.
        """
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        state.last_channel_id = ctx.channel.id
        await self._delete_last_status_message(guild_id)
        msg = await ctx.send(content=content, embed=embed, view=view)
        state.last_status_msg_id = msg.id
        return msg

    def _buffer_playback_error(self, guild_id: int, title: str) -> None:
        buf = self._playback_error_buffers.setdefault(guild_id, [])
        if title:
            buf.append(title)

        if guild_id in self._playback_error_flush_tasks and not self._playback_error_flush_tasks[guild_id].done():
            return
        self._playback_error_flush_tasks[guild_id] = asyncio.create_task(self._flush_playback_errors(guild_id))

    async def _flush_playback_errors(self, guild_id: int) -> None:
        # Short delay to batch consecutive failures.
        await asyncio.sleep(3)
        titles = self._playback_error_buffers.pop(guild_id, [])
        if not titles:
            return

        state = self.states.get(guild_id)
        channel_id = state.last_channel_id if state else None
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return

        # Keep message compact to avoid spam.
        unique = list(dict.fromkeys(titles))
        shown = unique[:3]
        more = max(0, len(unique) - len(shown))
        shown_text = ", ".join(f"**{t}**" for t in shown if isinstance(t, str))
        suffix = f" (+{more} lagi)" if more else ""
        await self._delete_last_status_message(guild_id)
        msg = await channel.send(f"⚠️ Beberapa lagu gagal diputar dan dilewati: {shown_text}{suffix}.")
        if state:
            state.last_status_msg_id = msg.id

    def _get_state(self, guild_id: int) -> GuildState:
        return self.states.get_or_create(guild_id)

    def _schedule_save_queues(self) -> None:
        if self._save_queues_task and not self._save_queues_task.done():
            return
        self._save_queues_task = asyncio.create_task(self._save_queues_async())

    async def _save_queues_async(self) -> None:
        await asyncio.to_thread(self.save_queues)

    def save_queues(self) -> None:
        try:
            data: Dict[str, Any] = {}
            for guild_id, state in self.states.states.items():
                if state.queue:
                    data[str(guild_id)] = state.queue
            # Ensure directory exists before writing
            if self.queue_file:
                os.makedirs(os.path.dirname(self.queue_file), exist_ok=True)
            with open(self.queue_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving queues: {e}")

    def load_queues(self) -> None:
        if os.path.exists(self.queue_file):
            try:
                with open(self.queue_file, 'r') as f:
                    data = json.load(f)
                for k, v in data.items():
                    try:
                        guild_id = int(k)
                    except Exception:
                        continue
                    state = self._get_state(guild_id)
                    if isinstance(v, list):
                        state.queue = v
                print("Loaded persistent queues.")
            except Exception as e:
                print(f"Error loading queues: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        # Voice Recovery
        if member.id == self.bot.user.id and before.channel and not after.channel:
            # Bot was disconnected
            guild_id = member.guild.id
            state = self._get_state(guild_id)
            if state.current_song:
                  # Bot was playing something, wait and try to reconnect
                  print(f"Bot disconnected from {member.guild.name}. Attempting recovery...")
                  await asyncio.sleep(2) # Add short delay
                  try:
                      vc = await before.channel.connect()
                      if state.current_song:
                           print("Reconnected! Resuming play_next...")
                           # Restart next
                           await self.play_recover(member.guild, vc)
                  except Exception as e:
                      print(f"Failed to recover voice connection: {e}")
                      
    async def play_recover(self, guild: discord.Guild, vc: discord.VoiceClient) -> None:
         # Resumes execution with the current song / queue if possible
         guild_id = guild.id
         state = self._get_state(guild_id)
         if state.current_song:
             entry = cast(Dict[str, Any], state.current_song)
             filename = await self._resolve_stream_url(entry)
             if not filename:
                 return
             source = discord.FFmpegPCMAudio(
                 filename,
                 before_options=self.ffmpeg_options['before_options'],
                 options=self.ffmpeg_options['options'],
             )
             source = discord.PCMVolumeTransformer(source)
             source.volume = state.volume
             vc.play(source, after=self._make_after_play(guild_id, vc, None))

    async def _resolve_stream_url(self, entry: Dict[str, Any]) -> Optional[str]:
        stream_url = entry.get('stream_url')
        if isinstance(stream_url, str) and stream_url.strip():
            refreshed = await self._refresh_stream_url(entry)
            if refreshed:
                entry['stream_url'] = refreshed
                return refreshed
            return stream_url

        search_query = entry.get('search_query')
        if isinstance(search_query, str) and search_query.strip():
            track_data = await self._search_playable(search_query)
            if track_data:
                entry['url'] = track_data.get('webpage_url') or entry.get('url')
                entry['stream_url'] = track_data.get('url')
                entry['title'] = track_data.get('title', entry.get('title') or search_query)
                entry['duration'] = track_data.get('duration')
                entry['thumbnail'] = track_data.get('thumbnail')
                resolved = entry.get('stream_url')
                if isinstance(resolved, str) and resolved.strip():
                    return resolved
            return None

        original_url = entry.get('url')
        if isinstance(original_url, str) and original_url.strip():
            data = await self._extract_info_async(original_url)
            if isinstance(data, dict):
                resolved = data.get('url')
                if isinstance(resolved, str) and resolved.strip():
                    entry['stream_url'] = resolved
                    entry.setdefault('title', data.get('title'))
                    entry.setdefault('duration', data.get('duration'))
                    entry.setdefault('thumbnail', data.get('thumbnail'))
                    entry.setdefault('url', data.get('webpage_url') or original_url)
                    return resolved
            # If URL extraction fails, fall back to searching by title.
            title = entry.get('title')
            if isinstance(title, str) and title.strip():
                track_data = await self._search_playable(title)
                if track_data:
                    entry['url'] = track_data.get('webpage_url') or original_url
                    entry['stream_url'] = track_data.get('url')
                    entry['title'] = track_data.get('title', title)
                    entry['duration'] = track_data.get('duration')
                    entry['thumbnail'] = track_data.get('thumbnail')
                    resolved = entry.get('stream_url')
                    if isinstance(resolved, str) and resolved.strip():
                        return resolved

        return None

    async def _refresh_stream_url(self, entry: Dict[str, Any]) -> Optional[str]:
        """Refresh potentially expired stream URL from original track URL."""
        original_url = entry.get('url')
        if not original_url:
            return entry.get('stream_url')

        data = await self._extract_info_async(original_url)
        if isinstance(data, dict):
            refreshed = data.get('url')
            if isinstance(refreshed, str) and refreshed.strip():
                return refreshed
        return entry.get('stream_url')

    def _make_after_play(
        self,
        guild_id: int,
        vc: Optional[discord.VoiceProtocol],
        ctx: Optional[commands.Context],
    ):
        def _after_play(err: Optional[Exception]) -> None:
            if err:
                print(f"FFmpeg playback error on guild {guild_id}: {err}")
            asyncio.run_coroutine_threadsafe(self.play_next_internal(guild_id, vc, ctx), self.bot.loop)

        return _after_play

    async def play_next(self, ctx: commands.Context) -> None:
        await self.play_next_internal(ctx.guild.id, ctx.voice_client, ctx)
        
    async def play_next_internal(self, guild_id: int, vc: Optional[discord.VoiceProtocol], ctx: Optional[commands.Context] = None) -> None:
        if not vc:
            return

        state = self._get_state(guild_id)
        loops = state.loop_mode
        previous_song = state.current_song
        
        entry = None
        if loops == 1 and previous_song:
            entry = previous_song
        elif loops == 2 and previous_song:
            state.queue.append(previous_song)
            self._schedule_save_queues()
            
        if not entry:
            if state.queue:
                entry = state.queue.pop(0)
                self._schedule_save_queues()
            else:
                state.current_song = None
                return

        try:
            filename: Optional[str] = None
            last_resolve_error: Optional[Exception] = None
            for attempt in range(max(1, SEARCH_RESOLVE_MAX_RETRIES)):
                try:
                    filename = await self._resolve_stream_url(entry)
                    if filename:
                        break
                except Exception as resolve_error:
                    last_resolve_error = resolve_error

                # Give yt-dlp/network a bit more breathing room when many requests arrive.
                if attempt < SEARCH_RESOLVE_MAX_RETRIES - 1:
                    await asyncio.sleep(SEARCH_RESOLVE_RETRY_DELAY_SEC)

            if not filename:
                raise RuntimeError(
                    f"Stream URL resolution failed after {SEARCH_RESOLVE_MAX_RETRIES} attempt(s)"
                ) from last_resolve_error
            
            state.current_song = entry
            state.start_time = time.time()
            state.clear_pause_state()
            state.reset_votes()
            
            source = discord.FFmpegPCMAudio(
                filename,
                before_options=self.ffmpeg_options['before_options'],
                options=self.ffmpeg_options['options'],
            )
            source = discord.PCMVolumeTransformer(source)
            source.volume = state.volume

            if vc and vc.is_connected():
                 vc.play(source, after=self._make_after_play(guild_id, vc, ctx))
                 
                 if ctx:
                     state.last_channel_id = ctx.channel.id

                 if state.last_channel_id:
                     channel = ctx.channel if ctx else self.bot.get_channel(state.last_channel_id)
                     if channel and isinstance(channel, discord.abc.Messageable):
                         view = MusicPlayerView(self, guild_id)
                         loop_msg = ""
                         if loops == 1:
                             loop_msg = "🔂 Loop Current"
                         elif loops == 2:
                             loop_msg = "🔁 Loop All"

                         if state.last_np_msg_id:
                             try:
                                 old_msg = await channel.fetch_message(state.last_np_msg_id)
                                 await old_msg.delete()
                             except Exception:
                                 pass

                         title = entry.get('title', 'Unknown Title')
                         msg = await channel.send(f'Now playing: **{title}** {loop_msg}', view=view)
                         state.last_np_msg_id = msg.id
            
        except Exception as e:
            print(f"Error processing song: {e}")
            title = entry.get('title', 'Unknown Title')
            # Don't spam chat for bulk/playlist failures; batch errors instead.
            self._buffer_playback_error(guild_id, title)
            await self.play_next_internal(guild_id, vc, ctx)

    @commands.command(name='join', aliases=['j'])
    @ensure_voice()
    async def play_join(self, ctx: commands.Context) -> None:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
            if ctx.voice_client:
                await ctx.voice_client.move_to(channel)
            else:
                await channel.connect()
            await self._send_status(ctx, content=f'Joined {channel}')
        else:
            await self._send_status(ctx, content='You are not in a voice channel!')

    @commands.command(name='leave', aliases=['l', 'dc'])
    @ensure_voice()
    async def play_leave(self, ctx: commands.Context) -> None:
        if ctx.voice_client:
            # Force disconnect to ensure underlying voice/ffmpeg resources are torn down.
            await ctx.voice_client.disconnect(force=True)
            state = self.states.remove(ctx.guild.id)
            if state:
                state.queue.clear()
                state.current_song = None
                state.reset_votes()
                await state.cleanup_message(self.bot)
                self._schedule_save_queues()
            await self._send_status(ctx, content='Left the channel')
        else:
            await self._send_status(ctx, content='I am not in a voice channel!')

    @commands.command(name='loop', aliases=['lp'])
    @ensure_voice()
    async def loop(self, ctx: commands.Context, mode: Optional[str] = None) -> None:
        state = self._get_state(ctx.guild.id)
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
                await self._send_status(ctx, content="Invalid loop mode. Use `all`, `current`, or `off`.")
                return
        else:
            new_state = (current_state + 1) % 3
            
        state.loop_mode = new_state
        msg = "Loop disabled ➡️"
        if new_state == 1:
            msg = "Looping **Current Song** 🔂"
        elif new_state == 2:
            msg = "Looping **Queue** 🔁"
        await self._send_status(ctx, content=msg)

    async def _extract_info_async(self, query: str) -> Optional[Dict[str, Any]]:
        return await extract_info_with_ytdl(self.ytdl, query)

    async def _pick_playable_entry(self, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Pick the first playable entry from search results.

        Some ytsearch top results can fail with format-unavailable errors.
        This method probes several candidates and returns one with a usable stream URL.
        """
        for candidate in entries[:10]:
            stream_url = candidate.get('url')
            # Accept pre-resolved direct media URLs immediately.
            if (
                isinstance(stream_url, str)
                and stream_url.strip()
                and stream_url.startswith(('http://', 'https://'))
                and 'youtube.com/watch' not in stream_url
                and 'youtu.be/' not in stream_url
            ):
                return candidate

            candidate_url = candidate.get('webpage_url') or candidate.get('original_url') or candidate.get('url')
            if not isinstance(candidate_url, str) or not candidate_url.strip():
                continue

            # yt-dlp search fallback can return bare YouTube video IDs; normalize to watch URL.
            if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate_url):
                candidate_url = f"https://www.youtube.com/watch?v={candidate_url}"

            resolved = await self._extract_info_async(candidate_url)
            if isinstance(resolved, dict):
                resolved_stream = resolved.get('url')
                if isinstance(resolved_stream, str) and resolved_stream.strip():
                    return resolved

        return None

    async def _search_playable(self, query: str) -> Optional[Dict[str, Any]]:
        """Search YouTube and return a playable entry (best-effort)."""
        query = (query or "").strip()
        if not query:
            return None

        # Try wider searches so one bad top result doesn't fail the whole request.
        for prefix in ("ytsearch1:", "ytsearch5:", "ytsearch10:", "ytsearch20:"):
            data = await self._extract_info_async(f"{prefix}{query}")
            if not data or "entries" not in data or not data["entries"]:
                continue
            candidate_entries = [e for e in data["entries"] if isinstance(e, dict)]
            chosen = await self._pick_playable_entry(candidate_entries)
            if chosen:
                return chosen
        return None



    @commands.command(name='play', aliases=['p'])
    @ensure_voice()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if not self.youtube_auth_ready:
            await self._send_status(
                ctx,
                content=(
                "⚠️ **Playback Unavailable**\n"
                "The bot is running in legacy mode and requires YouTube authentication, but no valid cookie file was found.\n"
                "Please configure `YOUTUBE_COOKIES` or `cookies.txt` to enable playback."
                ),
            )
            return
            
        state = self._get_state(ctx.guild.id)
        state.last_channel_id = ctx.channel.id
        if not ctx.voice_client:
            try:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect()
                else:
                    await self._send_status(ctx, content="You are not in a voice channel!")
                    return
            except Exception as e:
                await self._send_status(ctx, content=f"Could not join channel: {e}")
                return
            
        loop = asyncio.get_event_loop()

        if "spotify.com" in query or "spotify:" in query:
            await self._send_status(ctx, content="Spotify link detected. Fetching tracks...")
            tracks_to_search = []
            spotify_error: Optional[str] = None
            
            if self.sp:
                try:
                    # Need to use loop.run_in_executor for spotify calls too since they can be blocking network requests
                    if "track" in query:
                        track = await loop.run_in_executor(None, lambda: self.sp.track(query))
                        tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                    elif "playlist" in query:
                        results = await loop.run_in_executor(None, lambda: self.sp.playlist_tracks(query))
                        tracks = results['items']
                        while results['next']:
                            results = await loop.run_in_executor(None, lambda: self.sp.next(results))
                            tracks.extend(results['items'])
                        for item in tracks:
                            track = item.get('track')
                            if track:
                                tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                    elif "album" in query:
                        results = await loop.run_in_executor(None, lambda: self.sp.album_tracks(query))
                        tracks = results['items']
                        while results['next']:
                            results = await loop.run_in_executor(None, lambda: self.sp.next(results))
                            tracks.extend(results['items'])
                        for track in tracks:
                            tracks_to_search.append(f"{track['artists'][0]['name']} - {track['name']}")
                except Exception as e:
                    spotify_error = str(e)

            if not tracks_to_search:
                fallback_queries = await spotify_public_queries(query)
                if fallback_queries:
                    tracks_to_search = fallback_queries
                    if len(fallback_queries) == 1:
                        await self._send_status(ctx, content="Spotify API tidak tersedia, pakai fallback publik untuk track tunggal.")
                    else:
                        await self._send_status(
                            ctx,
                            content=f"Spotify API tidak tersedia, pakai fallback publik playlist/album ({len(fallback_queries)} track ditemukan).",
                        )
                elif spotify_error:
                    await self._send_status(ctx, content=f"Error fetching Spotify data: {spotify_error}")
                    return
                elif not self.sp:
                    await self._send_status(
                        ctx,
                        content="Spotify credentials tidak ditemukan, dan fallback publik tidak bisa membaca link Spotify ini.",
                    )
                    return

            if not tracks_to_search:
                 await self._send_status(ctx, content="No tracks found in Spotify link.")
                 return

            await self._send_status(ctx, content=f"Found {len(tracks_to_search)} tracks. Adding to queue...")

            first_query = tracks_to_search[0]
            track_data = await self._search_playable(first_query)
            if not track_data:
                await self._send_status(ctx, content=f"Could not find a playable YouTube result for **{first_query}**.")
                return

            entry = {
                'url': track_data.get('webpage_url'),
                'stream_url': track_data.get('url'),
                'title': track_data.get('title', first_query),
                'duration': track_data.get('duration'),
                'thumbnail': track_data.get('thumbnail'),
                'requester_id': ctx.author.id,
            }
            state.queue.append(entry)
            self._schedule_save_queues()
            
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await self.play_next(ctx)

            remaining = tracks_to_search[1:]
            for search_query in remaining:
                state.queue.append(
                    {
                        'search_query': search_query,
                        'title': search_query,
                        'requester_id': ctx.author.id,
                    }
                )
            if remaining:
                self._schedule_save_queues()
            await self._send_status(ctx, content=f"✅ Finished adding all {len(tracks_to_search)} Spotify tracks to queue.")
            return

        # Avoid spamming chat with progress messages; results will be posted after resolution.
        data = await self._extract_info_async(query)

        # Some yt-dlp builds fail to resolve plain-text queries with default_search.
        # Retry with explicit ytsearch to improve reliability for normal song titles.
        is_url_like = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', query) is not None or query.startswith('www.')
        if not data and not query.startswith('ytsearch:') and not is_url_like:
            data = await self._extract_info_async(f"ytsearch1:{query}")
        
        if not data:
            await self._send_status(
                ctx,
                content=(
                    "An error occurred or no songs found. "
                    "Try another keyword/title, or refresh YouTube cookies if this keeps happening."
                ),
            )
            return

        tracks_to_add = []
        if 'entries' in data:
            if data.get('_type') == 'playlist' and not query.startswith('ytsearch'):
                tracks_to_add = data['entries']
            else:
                candidate_entries = [e for e in data['entries'] if isinstance(e, dict)]
                chosen = await self._pick_playable_entry(candidate_entries)
                tracks_to_add = [chosen] if chosen else []
        else:
            tracks_to_add = [data]

        if not tracks_to_add:
            # Fallback: plain-text searches can sometimes return unplayable top results.
            fallback = await self._search_playable(query)
            if fallback:
                tracks_to_add = [fallback]
            else:
                await self._send_status(ctx, content="No songs found.")
                return

        added_count = 0
        for track in tracks_to_add:
            entry = {
                'url': track.get('original_url') or track.get('webpage_url') or track.get('url'),
                'stream_url': track.get('url'),
                'title': track.get('title', 'Unknown Title'),
                'duration': track.get('duration'),
                'thumbnail': track.get('thumbnail'),
                'requester_id': ctx.author.id
            }
            state.queue.append(entry)
            added_count += 1
        
        self._schedule_save_queues()
        
        if added_count == 1:
            await self._send_status(ctx, content=f"Added to queue: **{tracks_to_add[0].get('title')}**")
        else:
            await self._send_status(ctx, content=f"Added **{added_count}** songs to queue.")

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx)

    @commands.command(name='pause', aliases=['ps'])
    @ensure_voice()
    async def pause(self, ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_playing():
            state = self._get_state(ctx.guild.id)
            ctx.voice_client.pause()
            state.pause_start = time.time()
            await self._send_status(ctx, content="Paused ⏸️")

    @commands.command(name='resume', aliases=['res'])
    @ensure_voice()
    async def resume(self, ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_paused():
            state = self._get_state(ctx.guild.id)
            ctx.voice_client.resume()
            if state.pause_start:
                paused_duration = time.time() - state.pause_start
                if state.start_time:
                    state.start_time += paused_duration
                state.pause_start = None
            await self._send_status(ctx, content="Resumed ▶️")

    @commands.command(name='stop', aliases=['st'])
    @ensure_voice()
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.voice_client:
            await self._send_status(ctx, content="Not connected to a voice channel.")
            return
            
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        current = state.current_song
        
        can_stop = False
        if current and current.get('requester_id') == ctx.author.id:
            can_stop = True
        elif ctx.author.guild_permissions.administrator:
            can_stop = True
            
        if not can_stop:
            if ctx.author.id in state.stop_votes:
                await self._send_status(ctx, content="You have already voted to stop.")
                return
                
            state.stop_votes.add(ctx.author.id)
            votes_needed = _votes_needed(ctx.voice_client) if ctx.voice_client else 3
            current_votes = len(state.stop_votes)
            if current_votes < votes_needed:
                await self._send_status(ctx, embed=_make_vote_embed("stop", current_votes, votes_needed, ctx.author))
                return
                
        ctx.voice_client.stop()
        state.queue.clear()
        state.current_song = None
        state.loop_mode = 0
        state.reset_votes()
        await state.cleanup_message(self.bot)
        self._schedule_save_queues()

        await self._send_status(ctx, content="⏹️ Stopped and cleared queue.")

    @commands.command(name='queue', aliases=['q'])
    @ensure_voice()
    async def queue(self, ctx: commands.Context) -> None:
        state = self._get_state(ctx.guild.id)
        current_title = None
        if state.current_song and isinstance(state.current_song, dict):
            current_title = state.current_song.get("title")

        if state.queue:
            queue_list = state.queue
            view = QueuePaginationView(ctx, queue_list, current_title=current_title)
            embed = view.get_embed()
            view.update_buttons()
            await self._send_status(ctx, embed=embed, view=view)
            return

        if current_title:
            embed = discord.Embed(title="Queue", color=discord.Color.blue())
            embed.add_field(name="Now Playing", value=f"**{current_title}**", inline=False)
            embed.add_field(name="Up Next", value="(empty)", inline=False)
            await self._send_status(ctx, embed=embed)
            return

        await self._send_status(ctx, content="Queue is empty.")

    @commands.command(name='skip', aliases=['s', 'next'])
    @ensure_voice()
    async def skip(self, ctx: commands.Context, index: Optional[int] = None) -> None:
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            await self._send_status(ctx, content="Nothing is playing.")
            return
            
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        current = state.current_song
        
        can_skip = False
        if current and current.get('requester_id') == ctx.author.id:
            can_skip = True
        elif ctx.author.guild_permissions.administrator:
            can_skip = True
            
        if not can_skip:
            if ctx.author.id in state.skip_votes:
                await self._send_status(ctx, content="You have already voted to skip.")
                return
            state.skip_votes.add(ctx.author.id)
            votes_needed = _votes_needed(ctx.voice_client) if ctx.voice_client else 3
            current_votes = len(state.skip_votes)
            if current_votes < votes_needed:
                await self._send_status(ctx, embed=_make_vote_embed("skip", current_votes, votes_needed, ctx.author))
                return
                
        if index is not None:
            if not state.queue:
                await self._send_status(ctx, content="Queue is empty, cannot skip to specific index.")
                return
            if index < 1 or index > len(state.queue):
                 await self._send_status(ctx, content=f"Invalid index. Please provide a number between 1 and {len(state.queue)}.")
                 return
            target_song = state.queue.pop(index-1)
            state.queue.insert(0, target_song)
            self._schedule_save_queues()
            await self._send_status(ctx, content=f"⏭️ Skipping to **{target_song['title']}**...")
            ctx.voice_client.stop()
        else:
            ctx.voice_client.stop()
            await self._send_status(ctx, content="⏭️ Skipped song.")

    @commands.command(name='remove', aliases=['r', 'rm'])
    @ensure_voice()
    async def remove_from_queue(self, ctx: commands.Context, *, target: str) -> None:
        """Remove queue item(s). Supports compatibility syntax like `!r cl 10`."""
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.queue:
            await self._send_status(ctx, content="Queue is empty.")
            return

        tokens = target.strip().split()
        if not tokens:
            await self._send_status(ctx, content="Usage: `!remove <index>` or `!remove clear [index]`.")
            return

        first = tokens[0].lower()

        if first in {'cl', 'clear', 'clean'}:
            if len(tokens) == 1:
                removed_count = len(state.queue)
                state.queue = []
                self._schedule_save_queues()
                await self._send_status(ctx, content=f"🧹 Cleared queue ({removed_count} song(s)).")
                return

            if not tokens[1].isdigit():
                await self._send_status(ctx, content="Invalid index. Use a number after `clear`.")
                return

            index = int(tokens[1])
        else:
            if not first.isdigit():
                await self._send_status(ctx, content="Invalid syntax. Use `!remove <index>` or `!remove clear [index]`.")
                return
            index = int(first)

        queue = state.queue
        if index < 1 or index > len(queue):
            await self._send_status(ctx, content=f"Invalid index. Please provide a number between 1 and {len(queue)}.")
            return

        removed = queue.pop(index - 1)
        self._schedule_save_queues()
        await self._send_status(ctx, content=f"🗑️ Removed from queue: **{removed.get('title', 'Unknown Title')}**")

    @commands.command(name='clear', aliases=['cq', 'clearqueue'])
    @ensure_voice()
    async def clear_queue(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.queue:
            await self._send_status(ctx, content="Queue is already empty.")
            return

        removed_count = len(state.queue)
        state.queue = []
        self._schedule_save_queues()
        await self._send_status(ctx, content=f"🧹 Cleared queue ({removed_count} song(s)).")

    @commands.command(name='volume', aliases=['v', 'vol'])
    @ensure_voice()
    async def volume(self, ctx: commands.Context, volume: int) -> None:
        if ctx.voice_client is None:
            await self._send_status(ctx, content="Not connected to a voice channel.")
            return
        if volume < 0 or volume > 100:
            await self._send_status(ctx, content="Volume must be between 0 and 100.")
            return
        state = self._get_state(ctx.guild.id)
        state.volume = volume / 100
        if ctx.voice_client.source:
            if hasattr(ctx.voice_client.source, 'volume'):
                ctx.voice_client.source.volume = volume / 100
        await self._send_status(ctx, content=f"🔊 Volume set to **{volume}%**")

    @commands.command(name='nowplaying', aliases=['np', 'current'])
    @ensure_voice()
    async def now_playing(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.current_song:
            await self._send_status(ctx, content="Nothing is currently playing.")
            return
            
        entry = state.current_song
        current_time = 0
        if state.start_time:
            if state.pause_start:
                 current_time = state.pause_start - state.start_time
            else:
                 current_time = time.time() - state.start_time
        
        duration = entry.get('duration', 0)
        bar_length = 20
        if duration and duration > 0:
            progress = min(current_time / duration, 1.0)
            filled_len = int(progress * bar_length)
            bar = "▬" * filled_len + "🔘" + "▬" * (bar_length - filled_len)
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
        requester_id = entry.get('requester_id')
        requester = ctx.guild.get_member(cast(int, requester_id)) if requester_id is not None else None
        req_name = requester.display_name if requester else "Unknown"
        embed.set_footer(text=f"Requested by {req_name}", icon_url=requester.display_avatar.url if requester else None)
        await self._send_status(ctx, embed=embed)

class MusicPlayerView(discord.ui.View):
    def __init__(self, cog: "Music", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
             await interaction.response.send_message("You need to be in a voice channel to use this button.", ephemeral=True)
             return False
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc and vc.channel != interaction.user.voice.channel:
             await interaction.response.send_message("You need to be in the same voice channel as the bot to use this button.", ephemeral=True)
             return False
        return True

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="music_pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if not vc or not (vc.is_playing() or vc.is_paused()):
             await interaction.response.send_message("Nothing is playing!", ephemeral=True)
             return

        state = self.cog._get_state(self.guild_id)
        
        if vc.is_paused():
            vc.resume()
            if state.pause_start:
                paused_duration = time.time() - state.pause_start
                if state.start_time:
                    state.start_time += paused_duration
                state.pause_start = None
            state.pause_votes.clear()
            await interaction.response.send_message("▶️ Resumed", ephemeral=True)
        else:
            if interaction.user.guild_permissions.administrator:
                vc.pause()
                state.pause_start = time.time()
                state.pause_votes.clear()
                await interaction.response.send_message("⏸️ Paused", ephemeral=True)
                return
            if interaction.user.id in state.pause_votes:
                return await interaction.response.send_message("You have already voted to pause.", ephemeral=True)

            state.pause_votes.add(interaction.user.id)
            votes_needed = self._votes_needed(vc)
            current_votes = len(state.pause_votes)
            if current_votes < votes_needed:
                return await interaction.response.send_message(
                    embed=_make_vote_embed("pause", current_votes, votes_needed, interaction.user)
                )

            vc.pause()
            state.pause_start = time.time()
            state.pause_votes.clear()
            await interaction.response.send_message("⏸️ Paused")

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("Nothing to skip", ephemeral=True)
            
        state = self.cog._get_state(self.guild_id)
        current = state.current_song
        
        can_skip = interaction.user.guild_permissions.administrator
            
        if not can_skip:
            if interaction.user.id in state.skip_votes:
                return await interaction.response.send_message("You have already voted to skip.", ephemeral=True)
            state.skip_votes.add(interaction.user.id)
            votes_needed = self._votes_needed(vc)
            current_votes = len(state.skip_votes)
            if current_votes < votes_needed:
                return await interaction.response.send_message(
                    embed=_make_vote_embed("skip", current_votes, votes_needed, interaction.user)
                )
        vc.stop()
        await interaction.response.send_message("⏭️ Skipped")

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.success, custom_id="music_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        state = self.cog._get_state(self.guild_id)
        current_state = state.loop_mode
        new_state = (current_state + 1) % 3
        state.loop_mode = new_state
        msg = "Loop disabled ➡️"
        if new_state == 1: msg = "Looping **Current Song** 🔂"
        elif new_state == 2: msg = "Looping **Queue** 🔁"
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        vc = interaction.guild.voice_client if interaction.guild else None
        if not vc:
            return await interaction.response.send_message("Not connected", ephemeral=True)
            
        state = self.cog._get_state(self.guild_id)
        current = state.current_song
        
        can_stop = interaction.user.guild_permissions.administrator
            
        if not can_stop:
            if interaction.user.id in state.stop_votes:
                return await interaction.response.send_message("You have already voted to stop.", ephemeral=True)
            state.stop_votes.add(interaction.user.id)
            votes_needed = self._votes_needed(vc)
            current_votes = len(state.stop_votes)
            if current_votes < votes_needed:
                return await interaction.response.send_message(
                    embed=_make_vote_embed("stop", current_votes, votes_needed, interaction.user)
                )
        vc.stop()
        state.queue.clear()
        state.current_song = None
        state.loop_mode = 0
        state.reset_votes()
        await state.cleanup_message(self.cog.bot)
        self.cog._schedule_save_queues()
        await interaction.response.send_message("⏹️ Stopped and queue cleared")

    def _votes_needed(self, vc: discord.VoiceProtocol) -> int:
        return _votes_needed(vc)

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="music_queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        state = self.cog._get_state(self.guild_id)
        current_title = None
        if state.current_song and isinstance(state.current_song, dict):
            current_title = state.current_song.get("title")

        queue_list = state.queue or []
        max_lines = 10
        upcoming = "\n".join([f"{i+1}. {entry.get('title', 'Unknown')}" for i, entry in enumerate(queue_list[:max_lines])])
        if len(queue_list) > max_lines:
            upcoming += f"\n... and {len(queue_list) - max_lines} more."

        now_playing_line = f"**Now Playing:** {current_title}\n" if current_title else ""
        if queue_list:
            await interaction.response.send_message(
                f"{now_playing_line}**Up Next ({len(queue_list)}):**\n{upcoming}",
                ephemeral=True,
            )
        elif current_title:
            await interaction.response.send_message(f"{now_playing_line}**Up Next:** (empty)", ephemeral=True)
        else:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)

class QueuePaginationView(discord.ui.View):
    def __init__(self, ctx: commands.Context, queue_list: List[Dict[str, Any]], *, current_title: Optional[str] = None):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.queue_list = queue_list
        self.current_title = current_title
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(queue_list) - 1) // self.items_per_page + 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
             await interaction.response.send_message("You need to be in a voice channel to use this button.", ephemeral=True)
             return False
        vc = interaction.guild.voice_client
        if vc and vc.channel != interaction.user.voice.channel:
             await interaction.response.send_message("You need to be in the same voice channel as the bot.", ephemeral=True)
             return False
        return True

    def update_buttons(self) -> None:
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = self.current_page == self.total_pages - 1

    def get_embed(self) -> discord.Embed:
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_items = self.queue_list[start:end]
        
        queue_str = "\n".join([f"{start + i + 1}. {entry['title']}" for i, entry in enumerate(current_items)])
        embed = discord.Embed(title=f"Up Next ({len(self.queue_list)} songs)", description=queue_str, color=discord.Color.blue())
        if self.current_title:
            embed.add_field(name="Now Playing", value=f"**{self.current_title}**", inline=False)
        embed.set_footer(text=f"Page {self.current_page + 1}/{self.total_pages}")
        return embed

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.defer()
            
    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
