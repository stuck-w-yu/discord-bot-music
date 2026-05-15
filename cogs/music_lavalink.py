import asyncio
import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Union
import urllib.parse
import urllib.request

import discord
from discord.ext import commands
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import wavelink

from cogs.guild_state import GuildStateManager, GuildState


def ensure_voice():
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            raise commands.CommandError("You need to be in a voice channel to use this command.")

        if ctx.voice_client and ctx.voice_client.channel != ctx.author.voice.channel:
            raise commands.CommandError("You need to be in the same voice channel as the bot to use this command.")

        return True

    return commands.check(predicate)


class MusicLavalink(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states = GuildStateManager()
        self.node_connected = False

        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        if client_id and client_secret:
            self.sp = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
            )
        else:
            self.sp = None
            print("Spotify credentials not found. Spotify support disabled.")

    async def cog_load(self) -> None:
        self.bot.loop.create_task(self._connect_lavalink())

    async def _connect_lavalink(self) -> None:
        await self.bot.wait_until_ready()

        if wavelink.Pool.nodes:
            self.node_connected = True
            return

        host = os.getenv("LAVALINK_HOST", "lavalink")
        port = int(os.getenv("LAVALINK_PORT", "2333"))
        password = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")
        secure = os.getenv("LAVALINK_SECURE", "false").lower() == "true"

        node = wavelink.Node(uri=f"{'https' if secure else 'http'}://{host}:{port}", password=password)

        for attempt in range(1, 11):
            try:
                await wavelink.Pool.connect(nodes=[node], client=self.bot)
                self.node_connected = True
                print(f"Connected to Lavalink node on attempt {attempt}.")
                return
            except Exception as e:
                print(f"Lavalink connect failed (attempt {attempt}/10): {e}")
                await asyncio.sleep(3)

        print("Failed to connect to Lavalink. Music commands will be unavailable until node is reachable.")

    async def _ensure_player(self, ctx: commands.Context) -> wavelink.Player:
        if not self.node_connected and not wavelink.Pool.nodes:
            raise commands.CommandError("Lavalink is not connected yet. Please try again in a few seconds.")

        player = ctx.voice_client
        if isinstance(player, wavelink.Player):
            return player

        channel = ctx.author.voice.channel
        player = await channel.connect(cls=wavelink.Player, self_deaf=True)
        state = self.states.get_or_create(ctx.guild.id)
        await player.set_volume(int(state.volume * 100))
        return player

    def _is_url(self, query: str) -> bool:
        return query.startswith("http://") or query.startswith("https://")

    def _requester_from_track(self, track: Optional[wavelink.Playable]) -> Optional[int]:
        if not track:
            return None

        extras = getattr(track, "extras", None)
        if isinstance(extras, dict):
            return extras.get("requester_id")
        if extras is not None:
            return getattr(extras, "requester_id", None)
        return None

    async def _search_single_track(self, query: str) -> Optional[wavelink.Playable]:
        searches = [query] if self._is_url(query) else [f"ytsearch:{query}", query]

        for term in searches:
            result = await wavelink.Playable.search(term)
            if not result:
                continue

            if isinstance(result, wavelink.Playlist):
                return result.tracks[0] if result.tracks else None

            return result[0]

        return None

    async def _spotify_to_queries(self, query: str) -> List[str]:
        if not self.sp:
            raise commands.CommandError("Spotify support is not configured (missing credentials).")

        loop = asyncio.get_event_loop()
        queries: List[str] = []

        if "track" in query:
            track = await loop.run_in_executor(None, lambda: self.sp.track(query))
            queries.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif "playlist" in query:
            results = await loop.run_in_executor(None, lambda: self.sp.playlist_tracks(query))
            items = list(results["items"])
            while results["next"]:
                results = await loop.run_in_executor(None, lambda: self.sp.next(results))
                items.extend(results["items"])

            for item in items:
                track = item.get("track")
                if track:
                    queries.append(f"{track['artists'][0]['name']} - {track['name']}")
        elif "album" in query:
            results = await loop.run_in_executor(None, lambda: self.sp.album_tracks(query))
            items = list(results["items"])
            while results["next"]:
                results = await loop.run_in_executor(None, lambda: self.sp.next(results))
                items.extend(results["items"])

            for track in items:
                queries.append(f"{track['artists'][0]['name']} - {track['name']}")

        return queries

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
        track_query = await self._spotify_public_track_query(query)
        if track_query:
            return [track_query]

        if "playlist" in query or "album" in query:
            return await self._spotify_public_collection_queries(query)

        return []

    async def _start_next(self, guild_id: int, player: wavelink.Player) -> None:
        if player.playing or player.paused:
            return

        if player.queue.is_empty:
            state = self.states.get_or_create(guild_id)
            state.current_song = None
            return

        track = player.queue.get()
        state = self.states.get_or_create(guild_id)
        state.current_song = track
        state.skip_votes.clear()
        state.stop_votes.clear()
        await player.play(track, volume=int(state.volume * 100))

        # Send Now Playing message with buttons
        channel_id = state.last_channel_id
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.abc.Messageable):
                view = MusicPlayerView(self, channel)

                # Delete old NP message
                if state.last_np_msg_id:
                    try:
                        old_msg = await channel.fetch_message(state.last_np_msg_id)
                        await old_msg.delete()
                    except Exception:
                        pass

                loop_mode = state.loop_mode
                loop_msg = ""
                if loop_mode == 1: loop_msg = "🔂 Loop Current"
                elif loop_mode == 2: loop_msg = "🔁 Loop All"

                msg = await channel.send(f"Now playing: **{track.title}** {loop_msg}", view=view)
                state.last_np_msg_id = msg.id

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload) -> None:
        player = payload.player
        if not player or not player.guild:
            return

        guild_id = player.guild.id
        ended_track = payload.track
        state = self.states.get_or_create(guild_id)
        loop_mode = state.loop_mode

        if loop_mode == 1 and ended_track:
            try:
                player.queue.put_at(0, ended_track)
            except Exception:
                await player.queue.put_wait(ended_track)
        elif loop_mode == 2 and ended_track:
            await player.queue.put_wait(ended_track)

        await self._start_next(guild_id, player)

    @commands.command(name="join", aliases=["j"])
    @ensure_voice()
    async def play_join(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        channel = ctx.author.voice.channel

        if isinstance(player, wavelink.Player):
            await player.move_to(channel)
        else:
            await channel.connect(cls=wavelink.Player, self_deaf=True)

        await ctx.send(f"Joined {channel}")

    @commands.command(name="leave", aliases=["l", "dc"])
    @ensure_voice()
    async def play_leave(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if isinstance(player, wavelink.Player):
            await player.disconnect()
            state = self.states.remove(ctx.guild.id)
            if state:
                await state.cleanup_message(self.bot)

            await ctx.send("Left the channel")
            return

        await ctx.send("I am not in a voice channel!")

    @commands.command(name="play", aliases=["p"])
    @ensure_voice()
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        state = self.states.get_or_create(ctx.guild.id)
        state.last_channel_id = ctx.channel.id
        player = await self._ensure_player(ctx)

        if "spotify.com" in query or "spotify:" in query:
            await ctx.send("Spotify link detected. Fetching tracks...")
            queries: List[str] = []
            spotify_error: Optional[str] = None
            try:
                queries = await self._spotify_to_queries(query)
            except Exception as e:
                spotify_error = str(e)

            if not queries:
                fallback_queries = await self._spotify_public_queries(query)
                if fallback_queries:
                    queries = fallback_queries
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

            if not queries:
                return await ctx.send("No tracks found in Spotify link.")

            await ctx.send(f"Found {len(queries)} tracks. Resolving and adding to queue...")

            # Concurrent Spotify Loading
            sem = asyncio.Semaphore(3)
            added_count = 0

            async def fetch_and_queue(search_query: str) -> None:
                nonlocal added_count
                async with sem:
                    track = await self._search_single_track(search_query)
                    if track:
                        try:
                            track.extras = {"requester_id": ctx.author.id}
                        except Exception:
                            pass
                        await player.queue.put_wait(track)
                        added_count += 1

            # Resolve first track separately to start playing immediately
            first_track = await self._search_single_track(queries[0])
            if first_track:
                try:
                    first_track.extras = {"requester_id": ctx.author.id}
                except Exception:
                    pass
                await player.queue.put_wait(first_track)
                added_count += 1
                await self._start_next(ctx.guild.id, player)

            if len(queries) > 1:
                tasks = [fetch_and_queue(sq) for sq in queries[1:]]
                await asyncio.gather(*tasks)

            await ctx.send(f"✅ Finished adding all {added_count} Spotify tracks to queue.")
            return

        await ctx.send(f"Searching for **{query}**...")
        result = await wavelink.Playable.search(query if self._is_url(query) else f"ytsearch:{query}")

        if not result:
            return await ctx.send("No songs found.")

        if isinstance(result, wavelink.Playlist):
            for track in result.tracks:
                try:
                    track.extras = {"requester_id": ctx.author.id}
                except Exception:
                    pass
                await player.queue.put_wait(track)

            await ctx.send(f"Added playlist **{result.name}** with **{len(result.tracks)}** songs.")
        else:
            track = result[0]
            try:
                track.extras = {"requester_id": ctx.author.id}
            except Exception:
                pass
            await player.queue.put_wait(track)
            await ctx.send(f"Added to queue: **{track.title}**")

        await self._start_next(ctx.guild.id, player)

    @commands.command(name="pause", aliases=["ps"])
    @ensure_voice()
    async def pause(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if isinstance(player, wavelink.Player) and player.playing:
            await player.pause(True)
            await ctx.send("Paused ⏸️")

    @commands.command(name="resume", aliases=["res"])
    @ensure_voice()
    async def resume(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if isinstance(player, wavelink.Player) and player.paused:
            await player.pause(False)
            await ctx.send("Resumed ▶️")

    @commands.command(name="loop", aliases=["lp"])
    @ensure_voice()
    async def loop(self, ctx: commands.Context, mode: Optional[str] = None) -> None:
        state = self.states.get_or_create(ctx.guild.id)
        current_state = state.loop_mode

        if mode:
            mode = mode.lower()
            if mode == "all":
                new_state = 2
            elif mode in ["current", "song", "one"]:
                new_state = 1
            elif mode in ["off", "none", "disable"]:
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

    @commands.command(name="stop", aliases=["st"])
    @ensure_voice()
    async def stop(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            return await ctx.send("Not connected to a voice channel.")

        guild_id = ctx.guild.id
        state = self.states.get_or_create(guild_id)
        current = state.current_song

        can_stop = False
        if self._requester_from_track(current) == ctx.author.id:
            can_stop = True
        elif ctx.author.guild_permissions.administrator:
            can_stop = True

        if not can_stop:
            if ctx.author.id in state.stop_votes:
                return await ctx.send("You have already voted to stop.")

            state.stop_votes.add(ctx.author.id)
            votes_needed = 3
            current_votes = len(state.stop_votes)
            if current_votes < votes_needed:
                return await ctx.send(f"🗳️ Vote to **stop** registered. [{current_votes}/{votes_needed}]")

        player.queue.clear()
        await player.skip()
        state.current_song = None
        state.loop_mode = 0
        state.skip_votes.clear()
        state.stop_votes.clear()
        await state.cleanup_message(self.bot)
        await ctx.send("⏹️ Stopped and cleared queue.")

    @commands.command(name="skip", aliases=["s", "next"])
    @ensure_voice()
    async def skip(self, ctx: commands.Context, index: Optional[int] = None) -> None:
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or not (player.playing or player.paused):
            return await ctx.send("Nothing is playing.")

        guild_id = ctx.guild.id
        state = self.states.get_or_create(guild_id)
        current = state.current_song

        can_skip = False
        if self._requester_from_track(current) == ctx.author.id:
            can_skip = True
        elif ctx.author.guild_permissions.administrator:
            can_skip = True

        if not can_skip:
            if ctx.author.id in state.skip_votes:
                return await ctx.send("You have already voted to skip.")

            state.skip_votes.add(ctx.author.id)
            votes_needed = 3
            current_votes = len(state.skip_votes)
            if current_votes < votes_needed:
                return await ctx.send(f"🗳️ Vote to **skip** registered. [{current_votes}/{votes_needed}]")

        if index is not None:
            queue_items = list(player.queue)
            if not queue_items:
                return await ctx.send("Queue is empty, cannot skip to specific index.")
            if index < 1 or index > len(queue_items):
                return await ctx.send(f"Invalid index. Please provide a number between 1 and {len(queue_items)}.")

            target = queue_items.pop(index - 1)
            player.queue.clear()
            await player.queue.put_wait(target)
            for item in queue_items:
                await player.queue.put_wait(item)
            await ctx.send(f"⏭️ Skipping to **{target.title}**...")

        await player.skip()
        await ctx.send("⏭️ Skipped song.")

    @commands.command(name="remove", aliases=["r", "rm"])
    @ensure_voice()
    async def remove_from_queue(self, ctx: commands.Context, *, target: str) -> None:
        """Remove queue item(s). Supports compatibility syntax like `!r cl 10`."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            return await ctx.send("Queue is empty.")

        queue_items = list(player.queue)
        if not queue_items:
            return await ctx.send("Queue is empty.")

        tokens = target.strip().split()
        if not tokens:
            return await ctx.send("Usage: `!remove <index>` or `!remove clear [index]`.")

        first = tokens[0].lower()

        if first in {"cl", "clear", "clean"}:
            if len(tokens) == 1:
                removed_count = len(queue_items)
                player.queue.clear()
                return await ctx.send(f"🧹 Cleared queue ({removed_count} song(s)).")

            if not tokens[1].isdigit():
                return await ctx.send("Invalid index. Use a number after `clear`.")

            index = int(tokens[1])
        else:
            if not first.isdigit():
                return await ctx.send("Invalid syntax. Use `!remove <index>` or `!remove clear [index]`.")
            index = int(first)

        if index < 1 or index > len(queue_items):
            return await ctx.send(f"Invalid index. Please provide a number between 1 and {len(queue_items)}.")

        removed = queue_items.pop(index - 1)
        player.queue.clear()
        for item in queue_items:
            await player.queue.put_wait(item)

        await ctx.send(f"🗑️ Removed from queue: **{removed.title}**")

    @commands.command(name="clear", aliases=["cq", "clearqueue"])
    @ensure_voice()
    async def clear_queue(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            return await ctx.send("Queue is already empty.")

        queue_items = list(player.queue)
        if not queue_items:
            return await ctx.send("Queue is already empty.")

        removed_count = len(queue_items)
        player.queue.clear()
        await ctx.send(f"🧹 Cleared queue ({removed_count} song(s)).")

    @commands.command(name="queue", aliases=["q"])
    @ensure_voice()
    async def queue(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            return await ctx.send("Queue is empty.")

        queue_items = list(player.queue)
        if not queue_items:
            return await ctx.send("Queue is empty.")

        max_lines = 10
        queue_str = "\n".join([f"{i + 1}. {item.title}" for i, item in enumerate(queue_items[:max_lines])])
        if len(queue_items) > max_lines:
            queue_str += f"\n... and {len(queue_items) - max_lines} more."

        await ctx.send(f"**Current Queue ({len(queue_items)} songs):**\n{queue_str}")

    @commands.command(name="volume", aliases=["v", "vol"])
    @ensure_voice()
    async def volume(self, ctx: commands.Context, volume: int) -> None:
        if volume < 0 or volume > 100:
            return await ctx.send("Volume must be between 0 and 100.")

        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            return await ctx.send("Not connected to a voice channel.")

        state = self.states.get_or_create(ctx.guild.id)
        state.volume = volume / 100
        await player.set_volume(volume)
        await ctx.send(f"🔊 Volume set to **{volume}%**")

    @commands.command(name="nowplaying", aliases=["np", "current"])
    @ensure_voice()
    async def now_playing(self, ctx: commands.Context) -> None:
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or not player.current:
            return await ctx.send("Nothing is currently playing.")

        track = player.current
        position_ms = max(0, int(player.position))
        duration_ms = int(track.length or 0)

        if duration_ms > 0:
            progress = min(position_ms / duration_ms, 1.0)
            bar_len = 20
            filled = int(progress * bar_len)
            bar = "▬" * filled + "🔘" + "▬" * (bar_len - filled)
            current_str = str(datetime.timedelta(seconds=position_ms // 1000))
            total_str = str(datetime.timedelta(seconds=duration_ms // 1000))
            time_str = f"{current_str} / {total_str}"
        else:
            bar = "🔘" + "▬" * 20
            current_str = str(datetime.timedelta(seconds=position_ms // 1000))
            time_str = f"{current_str} / Live"

        embed = discord.Embed(
            title="Now Playing 🎵",
            description=f"[{track.title}]({track.uri or ''})",
            color=discord.Color.blue(),
        )
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)

        embed.add_field(name="Progress", value=f"`{time_str}`\n`{bar}`", inline=False)
        requester_id = self._requester_from_track(track)
        requester = ctx.guild.get_member(requester_id) if requester_id else None
        req_name = requester.display_name if requester else "Unknown"
        embed.set_footer(
            text=f"Requested by {req_name}",
            icon_url=requester.display_avatar.url if requester else None,
        )
        await ctx.send(embed=embed)


class MusicPlayerView(discord.ui.View):
    def __init__(self, cog: MusicLavalink, channel: discord.abc.Messageable):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild = getattr(channel, 'guild', None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
             await interaction.response.send_message("You need to be in a voice channel to use this button.", ephemeral=True)
             return False
        vc = interaction.guild.voice_client
        if vc and vc.channel != interaction.user.voice.channel:
             await interaction.response.send_message("You need to be in the same voice channel as the bot to use this button.", ephemeral=True)
             return False
        return True

    @discord.ui.button(label="⏯️ Pause/Resume", style=discord.ButtonStyle.primary, custom_id="lavalink_pause_resume")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player: wavelink.Player = interaction.guild.voice_client # type: ignore
        if not player or not player.current:
             await interaction.response.send_message("Nothing is playing!", ephemeral=True)
             return
        
        if player.paused:
            await player.pause(False)
            await interaction.response.send_message("▶️ Resumed", ephemeral=True)
        else:
            await player.pause(True)
            await interaction.response.send_message("⏸️ Paused", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, custom_id="lavalink_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player: wavelink.Player = interaction.guild.voice_client # type: ignore
        if not player or not player.current:
            return await interaction.response.send_message("Nothing to skip", ephemeral=True)
            
        await player.skip()
        await interaction.response.send_message("⏭️ Skipped")

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.success, custom_id="lavalink_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        guild_id = interaction.guild.id
        current_state = self.cog.loops.get(guild_id, 0)
        new_state = (current_state + 1) % 3
        self.cog.loops[guild_id] = new_state
        msg = "Loop disabled ➡️"
        if new_state == 1: msg = "Looping **Current Song** 🔂"
        elif new_state == 2: msg = "Looping **Queue** 🔁"
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger, custom_id="lavalink_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player: wavelink.Player = interaction.guild.voice_client # type: ignore
        if not player:
            return await interaction.response.send_message("Not connected", ephemeral=True)
            
        guild_id = interaction.guild.id
        player.queue.clear()
        await player.skip()
        self.cog.current_song[guild_id] = None
        self.cog.loops[guild_id] = 0
        await interaction.response.send_message("⏹️ Stopped and queue cleared")

    @discord.ui.button(label="📜 Queue", style=discord.ButtonStyle.secondary, custom_id="lavalink_queue")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        player: wavelink.Player = interaction.guild.voice_client # type: ignore
        if not player or player.queue.is_empty:
            return await interaction.response.send_message("Queue is empty.", ephemeral=True)
            
        queue_items = list(player.queue)
        max_lines = 10
        queue_str = "\n".join([f"{i+1}. {item.title}" for i, item in enumerate(queue_items[:max_lines])])
        if len(queue_items) > max_lines:
            queue_str += f"\n... and {len(queue_items) - max_lines} more."
        await interaction.response.send_message(f"**Current Queue ({len(queue_items)} songs):**\n{queue_str}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicLavalink(bot))
