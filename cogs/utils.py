import re
import json
import urllib.parse
import urllib.request
import asyncio
import yt_dlp
from typing import List, Optional, Any, Dict

import discord
from discord.ext import commands


def ensure_voice():
    async def predicate(ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            raise commands.CommandError("You need to be in a voice channel to use this command.")

        if ctx.voice_client and ctx.voice_client.channel != ctx.author.voice.channel:
            raise commands.CommandError("You need to be in the same voice channel as the bot to use this command.")

        return True

    return commands.check(predicate)


def spotify_track_url_from_query(query: str) -> Optional[str]:
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


def spotify_resource_id_from_query(query: str, resource: str) -> Optional[str]:
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


async def spotify_public_track_query(query: str) -> Optional[str]:
    track_url = spotify_track_url_from_query(query)
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


async def spotify_public_collection_queries(query: str) -> List[str]:
    resource = "playlist" if "playlist" in query else "album" if "album" in query else None
    if not resource:
        return []

    resource_id = spotify_resource_id_from_query(query, resource)
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


async def spotify_public_queries(query: str) -> List[str]:
    track_query = await spotify_public_track_query(query)
    if track_query:
        return [track_query]

    if "playlist" in query or "album" in query:
        return await spotify_public_collection_queries(query)

    return []


async def extract_info_with_ytdl(ytdl, query: str) -> Optional[Dict[str, Any]]:
    from cogs.extract_cache import ExtractInfoCache
    cache = getattr(extract_info_with_ytdl, 'cache', None)
    if cache is None:
        cache = ExtractInfoCache(max_size=100)
        extract_info_with_ytdl.cache = cache

    cached_data = cache.get(query)
    if cached_data is not None:
        return cached_data

    loop = asyncio.get_event_loop()

    def _looks_like_url(value: str) -> bool:
        return re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value) is not None or value.startswith('www.')

    def _extract_with_fallback() -> Optional[Dict[str, Any]]:
        try:
            return ytdl.extract_info(query, download=False)
        except Exception as primary_error:
            message = str(primary_error)
            if 'Requested format is not available' in message:
                try:
                    fallback_opts = dict(ytdl.params)
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
            cache.set(query, data)
        return data
    except Exception as e:
        print(f"Failed to extract info for {query}: {e}")
        return None