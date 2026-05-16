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
import urllib.parse
import urllib.request
import base64
from typing import Optional, Dict, List, Any, Set, cast, Union

from cogs.extract_cache import ExtractInfoCache
from cogs.guild_state import GuildStateManager, GuildState
from cogs.perf_config import OptimizedFFmpegOptions

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


# Custom Check
def ensure_voice():
    async def predicate(ctx: commands.Context) -> bool:
        # If the bot is already connected, allow queue/control commands even when the
        # message author isn't in a voice channel (e.g. forwarded commands from another bot).
        # If the author *is* in voice, still require them to be in the same channel.
        if ctx.voice_client and getattr(ctx.voice_client, "channel", None):
            if getattr(ctx.author, "voice", None) and ctx.author.voice:
                if ctx.voice_client.channel != ctx.author.voice.channel:
                    raise commands.CommandError(
                        "You need to be in the same voice channel as the bot to use this command."
                    )
            return True

        if not getattr(ctx.author, "voice", None) or not ctx.author.voice:
            raise commands.CommandError("You need to be in a voice channel to use this command.")

        return True
    return commands.check(predicate)

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.states = GuildStateManager()
        self.cache = ExtractInfoCache(max_size=100)
        self._save_queues_task: Optional[asyncio.Task[None]] = None
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
            data = await self._extract_info_async(f"ytsearch:{search_query}")
            if data and 'entries' in data and data['entries']:
                candidate_entries = [e for e in data['entries'] if isinstance(e, dict)]
                track_data = await self._pick_playable_entry(candidate_entries)
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
            filename = await self._resolve_stream_url(entry)
            if not filename:
                raise RuntimeError("Stream URL resolution failed")
            
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
            if ctx:
                title = entry.get('title', 'Unknown Title')
                await ctx.send(f"Error playing **{title}**. Skipping...")
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
            await ctx.send(f'Joined {channel}')
        else:
            await ctx.send('You are not in a voice channel!')

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
            await ctx.send('Left the channel')
        else:
            await ctx.send('I am not in a voice channel!')

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
                return await ctx.send("Invalid loop mode. Use `all`, `current`, or `off`.")
        else:
            new_state = (current_state + 1) % 3
            
        state.loop_mode = new_state
        msg = "Loop disabled ➡️"
        if new_state == 1:
            msg = "Looping **Current Song** 🔂"
        elif new_state == 2:
            msg = "Looping **Queue** 🔁"
        await ctx.send(msg)

    async def _extract_info_async(self, query: str) -> Optional[Dict[str, Any]]:
        cached_data = self.cache.get(query)
        if cached_data is not None:
            return cached_data

        loop = asyncio.get_event_loop()

        def _extract_with_fallback() -> Optional[Dict[str, Any]]:
            def _looks_like_url(value: str) -> bool:
                return re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value) is not None or value.startswith('www.')

            try:
                return self.ytdl.extract_info(query, download=False)
            except Exception as primary_error:
                message = str(primary_error)
                # Some videos/playlists expose no matching stream for strict format selectors.
                # Retry with relaxed options so search/metadata flow does not fail hard.
                if 'Requested format is not available' in message:
                    try:
                        fallback_opts = dict(self.yt_dlp_options)
                        fallback_opts.pop('format', None)
                        fallback_opts.pop('extractaudio', None)
                        fallback_opts.pop('audioformat', None)
                        fallback_opts['skip_download'] = True
                        fallback_opts['ignoreerrors'] = True
                        fallback_opts['extractor_args'] = {
                            'youtube': {
                                'player_client': ['android', 'web', 'tv']
                            }
                        }
                        with yt_dlp.YoutubeDL(fallback_opts) as fallback_ytdl:
                            result = fallback_ytdl.extract_info(query, download=False)
                            if result:
                                return result

                        # Extra fallback for plain-text search: use broader ytsearch so one broken
                        # candidate does not cause complete failure.
                        if not _looks_like_url(query) and not query.startswith('ytsearch:') and not query.startswith('ytsearch1:'):
                            with yt_dlp.YoutubeDL(fallback_opts) as fallback_ytdl:
                                return fallback_ytdl.extract_info(f"ytsearch5:{query}", download=False)
                    except Exception as fallback_error:
                        print(f"Fallback extract failed for {query}: {fallback_error}")
                        return None

                print(f"Failed to extract info for {query}: {primary_error}")
                return None

        try:
            data = await loop.run_in_executor(None, _extract_with_fallback)
            if data is not None:
                self.cache.set(query, data)
            return data
        except Exception as e:
            print(f"Failed to extract info for {query}: {e}")
            return None

    async def _pick_playable_entry(self, entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Pick the first playable entry from search results.

        Some ytsearch top results can fail with format-unavailable errors.
        This method probes several candidates and returns one with a usable stream URL.
        """
        for candidate in entries[:5]:
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

    def _spotify_track_url_from_query(self, query: str) -> Optional[str]:
        if "open.spotify.com/track/" in query:
            track_part = query.split("open.spotify.com/track/", 1)[1]
            track_id = track_part.split("?", 1)[0].split("/", 1)[0].strip()
            if track_id:
                return f"https://open.spotify.com/track/{track_id}"
            return None

        if query.startswith("spotify:track:"):
            parts = query.split(":")
            if len(parts) >= 3 and parts[2].strip():
                return f"https://open.spotify.com/track/{parts[2].strip()}"

        return None

    def _spotify_resource_id_from_query(self, query: str, resource: str) -> Optional[str]:
        web_token = f"open.spotify.com/{resource}/"
        if web_token in query:
            resource_part = query.split(web_token, 1)[1]
            resource_id = resource_part.split("?", 1)[0].split("/", 1)[0].strip()
            return resource_id or None

        uri_token = f"spotify:{resource}:"
        if query.startswith(uri_token):
            parts = query.split(":")
            if len(parts) >= 3 and parts[2].strip():
                return parts[2].strip()

        return None

    async def _spotify_public_track_query(self, query: str) -> Optional[str]:
        # Public fallback without Spotify API key; only supports single track links.
        track_url = self._spotify_track_url_from_query(query)
        if not track_url:
            return None

        oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(track_url, safe='')}"
        loop = asyncio.get_event_loop()

        def fetch_title() -> Optional[str]:
            try:
                req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                title = payload.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()
            except Exception:
                return None
            return None

        return await loop.run_in_executor(None, fetch_title)

    async def _spotify_public_collection_queries(self, query: str) -> List[str]:
        # Scrape playlist/album page data as a best-effort fallback when Spotify API is unavailable.
        resource = "playlist" if "playlist" in query else "album" if "album" in query else None
        if not resource:
            return []

        resource_id = self._spotify_resource_id_from_query(query, resource)
        if not resource_id:
            return []

        public_url = f"https://open.spotify.com/{resource}/{resource_id}"
        loop = asyncio.get_event_loop()

        def fetch_queries() -> List[str]:
            try:
                req = urllib.request.Request(
                    public_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    html = response.read().decode("utf-8", errors="ignore")

                next_data_match = re.search(
                    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                    html,
                    flags=re.DOTALL,
                )
                if not next_data_match:
                    return []

                payload = json.loads(next_data_match.group(1))
                queries: List[str] = []

                def walk(node: Any) -> None:
                    if isinstance(node, dict):
                        name_raw = node.get("name")
                        uri_raw = node.get("uri")
                        type_raw = node.get("type")
                        artists_raw = node.get("artists")

                        if isinstance(name_raw, str) and name_raw.strip():
                            is_track = (
                                (isinstance(uri_raw, str) and uri_raw.startswith("spotify:track:"))
                                or type_raw == "track"
                            )
                            if is_track:
                                title = name_raw.strip()
                                artist = ""
                                if isinstance(artists_raw, list) and artists_raw:
                                    first_artist = artists_raw[0]
                                    if isinstance(first_artist, dict):
                                        first_name = first_artist.get("name")
                                        if isinstance(first_name, str):
                                            artist = first_name.strip()

                                if artist and artist.lower() not in title.lower():
                                    queries.append(f"{artist} - {title}")
                                else:
                                    queries.append(title)

                        for value in node.values():
                            walk(value)
                        return

                    if isinstance(node, list):
                        for item in node:
                            walk(item)

                walk(payload)
                deduped = list(dict.fromkeys(queries))
                return deduped[:200]
            except Exception:
                return []

        return await loop.run_in_executor(None, fetch_queries)

    async def _spotify_public_queries(self, query: str) -> List[str]:
        # Best-effort fallback without Spotify API key.
        # For track links, use oEmbed title. For playlist/album, try yt-dlp first then page scraping.
        track_query = await self._spotify_public_track_query(query)
        if track_query:
            return [track_query]

        data = await self._extract_info_async(query)
        if not data:
            if "playlist" in query or "album" in query:
                return await self._spotify_public_collection_queries(query)
            return []

        entries: List[Dict[str, Any]] = []
        if isinstance(data, dict) and 'entries' in data and data['entries']:
            entries = [e for e in data['entries'] if isinstance(e, dict)]
        elif isinstance(data, dict):
            entries = [data]

        queries: List[str] = []
        for entry in entries:
            title = (entry.get('track') or entry.get('title') or '').strip()
            artist = (entry.get('artist') or entry.get('uploader') or '').strip()
            if not title:
                continue

            if artist and artist.lower() not in title.lower():
                queries.append(f"{artist} - {title}")
            else:
                queries.append(title)

        # De-duplicate while preserving order.
        deduped = list(dict.fromkeys(queries))
        if deduped:
            return deduped

        if "playlist" in query or "album" in query:
            return await self._spotify_public_collection_queries(query)

        return deduped

    @commands.command(name='play', aliases=['p'])
    @ensure_voice()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        if not self.youtube_auth_ready:
            return await ctx.send(
                "⚠️ **Playback Unavailable**\n"
                "The bot is running in legacy mode and requires YouTube authentication, but no valid cookie file was found.\n"
                "Please configure `YOUTUBE_COOKIES` or `cookies.txt` to enable playback."
            )
            
        state = self._get_state(ctx.guild.id)
        state.last_channel_id = ctx.channel.id
        if not ctx.voice_client:
            try:
                if ctx.author.voice:
                    await ctx.author.voice.channel.connect()
                else:
                    return await ctx.send("You are not in a voice channel!")
            except Exception as e:
                return await ctx.send(f"Could not join channel: {e}")
            
        loop = asyncio.get_event_loop()

        if "spotify.com" in query or "spotify:" in query:
            await ctx.send("Spotify link detected. Fetching tracks...")
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
                fallback_queries = await self._spotify_public_queries(query)
                if fallback_queries:
                    tracks_to_search = fallback_queries
                    if len(fallback_queries) == 1:
                        await ctx.send("Spotify API tidak tersedia, pakai fallback publik untuk track tunggal.")
                    else:
                        await ctx.send(
                            f"Spotify API tidak tersedia, pakai fallback publik playlist/album ({len(fallback_queries)} track ditemukan)."
                        )
                elif spotify_error:
                    return await ctx.send(f"Error fetching Spotify data: {spotify_error}")
                elif not self.sp:
                    return await ctx.send(
                        "Spotify credentials tidak ditemukan, dan fallback publik tidak bisa membaca link Spotify ini."
                    )

            if not tracks_to_search:
                 return await ctx.send("No tracks found in Spotify link.")

            await ctx.send(f"Found {len(tracks_to_search)} tracks. Adding to queue...")

            first_query = tracks_to_search[0]
            data = await self._extract_info_async(f"ytsearch:{first_query}")
            if data and 'entries' in data and data['entries']:
                candidate_entries = [e for e in data['entries'] if isinstance(e, dict)]
                track_data = await self._pick_playable_entry(candidate_entries)
                if not track_data:
                    return await ctx.send(f"Could not find a playable YouTube result for **{first_query}**.")

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
            else:
                 await ctx.send(f"Could not find **{first_query}** on YouTube.")

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
            await ctx.send(f"✅ Finished adding all {len(tracks_to_search)} Spotify tracks to queue.")
            return

        await ctx.send(f"Searching for **{query}**...")
        data = await self._extract_info_async(query)

        # Some yt-dlp builds fail to resolve plain-text queries with default_search.
        # Retry with explicit ytsearch to improve reliability for normal song titles.
        is_url_like = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', query) is not None or query.startswith('www.')
        if not data and not query.startswith('ytsearch:') and not is_url_like:
            data = await self._extract_info_async(f"ytsearch1:{query}")
        
        if not data:
            return await ctx.send(
                "An error occurred or no songs found. "
                "Try another keyword/title, or refresh YouTube cookies if this keeps happening."
            )

        tracks_to_add = []
        if 'entries' in data:
            if data.get('_type') == 'playlist' and not query.startswith('ytsearch'):
                tracks_to_add = data['entries']
                await ctx.send(f"Found playlist with {len(tracks_to_add)} songs.")
            else:
                candidate_entries = [e for e in data['entries'] if isinstance(e, dict)]
                chosen = await self._pick_playable_entry(candidate_entries)
                tracks_to_add = [chosen] if chosen else []
        else:
            tracks_to_add = [data]

        if not tracks_to_add:
            return await ctx.send("No songs found.")

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
            await ctx.send(f"Added to queue: **{tracks_to_add[0].get('title')}**")
        else:
            await ctx.send(f"Added **{added_count}** songs to queue.")

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_next(ctx)

    @commands.command(name='pause', aliases=['ps'])
    @ensure_voice()
    async def pause(self, ctx: commands.Context) -> None:
        if ctx.voice_client and ctx.voice_client.is_playing():
            state = self._get_state(ctx.guild.id)
            ctx.voice_client.pause()
            state.pause_start = time.time()
            await ctx.send("Paused ⏸️")

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
            await ctx.send("Resumed ▶️")

    @commands.command(name='stop', aliases=['st'])
    @ensure_voice()
    async def stop(self, ctx: commands.Context) -> None:
        if not ctx.voice_client:
            return await ctx.send("Not connected to a voice channel.")
            
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
                return await ctx.send("You have already voted to stop.")
                
            state.stop_votes.add(ctx.author.id)
            votes_needed = _votes_needed(ctx.voice_client) if ctx.voice_client else 3
            current_votes = len(state.stop_votes)
            if current_votes < votes_needed:
                return await ctx.send(embed=_make_vote_embed("stop", current_votes, votes_needed, ctx.author))
                
        ctx.voice_client.stop()
        state.queue.clear()
        state.current_song = None
        state.loop_mode = 0
        state.reset_votes()
        await state.cleanup_message(self.bot)
        self._schedule_save_queues()

        await ctx.send("⏹️ Stopped and cleared queue.")

    @commands.command(name='queue', aliases=['q'])
    @ensure_voice()
    async def queue(self, ctx: commands.Context) -> None:
        state = self._get_state(ctx.guild.id)
        if state.queue:
            queue_list = state.queue
            view = QueuePaginationView(ctx, queue_list)
            embed = view.get_embed()
            view.update_buttons()
            await ctx.send(embed=embed, view=view)
        else:
            await ctx.send("Queue is empty.")

    @commands.command(name='skip', aliases=['s', 'next'])
    @ensure_voice()
    async def skip(self, ctx: commands.Context, index: Optional[int] = None) -> None:
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            return await ctx.send("Nothing is playing.")
            
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
                return await ctx.send("You have already voted to skip.")
            state.skip_votes.add(ctx.author.id)
            votes_needed = _votes_needed(ctx.voice_client) if ctx.voice_client else 3
            current_votes = len(state.skip_votes)
            if current_votes < votes_needed:
                return await ctx.send(embed=_make_vote_embed("skip", current_votes, votes_needed, ctx.author))
                
        if index is not None:
            if not state.queue:
                return await ctx.send("Queue is empty, cannot skip to specific index.")
            if index < 1 or index > len(state.queue):
                 return await ctx.send(f"Invalid index. Please provide a number between 1 and {len(state.queue)}.")
            target_song = state.queue.pop(index-1)
            state.queue.insert(0, target_song)
            self._schedule_save_queues()
            await ctx.send(f"⏭️ Skipping to **{target_song['title']}**...")
            ctx.voice_client.stop()
        else:
            ctx.voice_client.stop()
            await ctx.send("⏭️ Skipped song.")

    @commands.command(name='remove', aliases=['r', 'rm'])
    @ensure_voice()
    async def remove_from_queue(self, ctx: commands.Context, *, target: str) -> None:
        """Remove queue item(s). Supports compatibility syntax like `!r cl 10`."""
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.queue:
            return await ctx.send("Queue is empty.")

        tokens = target.strip().split()
        if not tokens:
            return await ctx.send("Usage: `!remove <index>` or `!remove clear [index]`.")

        first = tokens[0].lower()

        if first in {'cl', 'clear', 'clean'}:
            if len(tokens) == 1:
                removed_count = len(state.queue)
                state.queue = []
                self._schedule_save_queues()
                return await ctx.send(f"🧹 Cleared queue ({removed_count} song(s)).")

            if not tokens[1].isdigit():
                return await ctx.send("Invalid index. Use a number after `clear`.")

            index = int(tokens[1])
        else:
            if not first.isdigit():
                return await ctx.send("Invalid syntax. Use `!remove <index>` or `!remove clear [index]`.")
            index = int(first)

        queue = state.queue
        if index < 1 or index > len(queue):
            return await ctx.send(f"Invalid index. Please provide a number between 1 and {len(queue)}.")

        removed = queue.pop(index - 1)
        self._schedule_save_queues()
        await ctx.send(f"🗑️ Removed from queue: **{removed.get('title', 'Unknown Title')}**")

    @commands.command(name='clear', aliases=['cq', 'clearqueue'])
    @ensure_voice()
    async def clear_queue(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.queue:
            return await ctx.send("Queue is already empty.")

        removed_count = len(state.queue)
        state.queue = []
        self._schedule_save_queues()
        await ctx.send(f"🧹 Cleared queue ({removed_count} song(s)).")

    @commands.command(name='volume', aliases=['v', 'vol'])
    @ensure_voice()
    async def volume(self, ctx: commands.Context, volume: int) -> None:
        if ctx.voice_client is None:
            return await ctx.send("Not connected to a voice channel.")
        if volume < 0 or volume > 100:
            return await ctx.send("Volume must be between 0 and 100.")
        state = self._get_state(ctx.guild.id)
        state.volume = volume / 100
        if ctx.voice_client.source:
            if hasattr(ctx.voice_client.source, 'volume'):
                ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"🔊 Volume set to **{volume}%**")

    @commands.command(name='nowplaying', aliases=['np', 'current'])
    @ensure_voice()
    async def now_playing(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id
        state = self._get_state(guild_id)
        if not state.current_song:
            return await ctx.send("Nothing is currently playing.")
            
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
        await ctx.send(embed=embed)

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
        if state.queue:
            queue_list = state.queue
            max_lines = 10
            queue_str = "\n".join([f"{i+1}. {entry['title']}" for i, entry in enumerate(queue_list[:max_lines])])
            if len(queue_list) > max_lines:
                queue_str += f"\n... and {len(queue_list) - max_lines} more."
            await interaction.response.send_message(f"**Current Queue ({len(queue_list)} songs):**\n{queue_str}", ephemeral=True)
        else:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)

class QueuePaginationView(discord.ui.View):
    def __init__(self, ctx: commands.Context, queue_list: List[Dict[str, Any]]):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.queue_list = queue_list
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
        embed = discord.Embed(title=f"Current Queue ({len(self.queue_list)} songs)", description=queue_str, color=discord.Color.blue())
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
