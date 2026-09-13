import re
import json
import urllib.parse
import urllib.request
import asyncio
import yt_dlp  # type: ignore
from typing import List, Optional, Any, Dict, Set

import discord
from discord.ext import commands


def ensure_voice():
    async def predicate(ctx: commands.Context) -> bool:
        if not isinstance(ctx.author, discord.Member) or not ctx.author.voice:
            raise commands.CommandError("You need to be in a voice channel to use this command.")

        bot_channel = getattr(ctx.voice_client, "channel", None)
        if ctx.voice_client and bot_channel and ctx.author.voice.channel != bot_channel:
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


_extract_cache: Optional[Any] = None


def _get_extract_cache():
    global _extract_cache
    if _extract_cache is None:
        from cogs.extract_cache import ExtractInfoCache
        _extract_cache = ExtractInfoCache(max_size=100)
    return _extract_cache


async def extract_info_with_ytdl(ytdl, query: str) -> Optional[Dict[str, Any]]:
    cache = _get_extract_cache()

    cached_data = cache.get(query)
    if cached_data is not None:
        return cached_data

    loop = asyncio.get_event_loop()

    def _looks_like_url(value: str) -> bool:
        return re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value) is not None or value.startswith('www.')

    def _extract_with_fallback() -> Optional[Dict[str, Any]]:
        def _is_usable(res: Any) -> bool:
            if not isinstance(res, dict):
                return False
            if 'entries' in res:
                return any(isinstance(e, dict) for e in res.get('entries', []))
            return True

        result = None
        try:
            result = ytdl.extract_info(query, download=False)
            if _is_usable(result):
                return result
        except Exception:
            pass

        # If primary failed or returned unusable data (e.g. HTTP 400 Bad Request from stale cookies)
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

        # Step 1: Retry without cookiefile (stale/expired cookies frequently trigger HTTP 400 on searches)
        if 'cookiefile' in fallback_opts:
            clean_opts = dict(fallback_opts)
            clean_opts.pop('cookiefile', None)
            try:
                with yt_dlp.YoutubeDL(clean_opts) as fallback_ytdl:
                    fb_res = fallback_ytdl.extract_info(query, download=False)
                    if _is_usable(fb_res):
                        return fb_res
                    if not _looks_like_url(query) and not query.startswith('ytsearch'):
                        fb_res = fallback_ytdl.extract_info(f"ytsearch5:{query}", download=False)
                        if _is_usable(fb_res):
                            return fb_res
            except Exception:
                pass

        # Step 2: Retry with client fallbacks
        try:
            with yt_dlp.YoutubeDL(fallback_opts) as fallback_ytdl:
                fb_res = fallback_ytdl.extract_info(query, download=False)
                if _is_usable(fb_res):
                    return fb_res
                if not _looks_like_url(query) and not query.startswith('ytsearch'):
                    fb_res = fallback_ytdl.extract_info(f"ytsearch5:{query}", download=False)
                    if _is_usable(fb_res):
                        return fb_res
        except Exception:
            pass

        return result if _is_usable(result) else None

    try:
        data = await loop.run_in_executor(None, _extract_with_fallback)
        if data is not None:
            cache.set(query, data)
        return data
    except Exception as e:
        print(f"Failed to extract info for {query}: {e}")
        return None


def extract_youtube_video_id(url_or_id: Optional[str]) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL or raw ID string."""
    if not url_or_id:
        return None
    cleaned = url_or_id.strip()
    if len(cleaned) == 11 and re.match(r'^[a-zA-Z0-9_-]{11}$', cleaned):
        return cleaned
    match = re.search(r'(?:v=|\/embed\/|youtu\.be\/|\/v\/|\/shorts\/)([a-zA-Z0-9_-]{11})', cleaned)
    if match:
        return match.group(1)
    return None


def _parse_duration_str(duration_str: Optional[str]) -> Optional[int]:
    """Parse 'MM:SS' or 'HH:MM:SS' duration string into seconds."""
    if not duration_str:
        return None
    parts = duration_str.split(':')
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, TypeError):
        return None
    return None


async def get_autoplay_recommendations(
    seed: str,
    limit: int = 5,
    exclude_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch recommended tracks from YouTube Music based on a seed (video ID, URL, or song title).
    Uses ytmusicapi with IPv4 connection optimization.
    """
    if not seed:
        return []

    exclude: Set[str] = set(exclude_ids) if exclude_ids else set()

    def _fetch_sync() -> List[Dict[str, Any]]:
        try:
            # Force IPv4 in urllib3 to avoid long IPv6 SYN timeouts on hosts without IPv6 routing
            try:
                import socket
                import urllib3.util.connection as urllib3_conn
                urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
            except Exception:
                pass

            from ytmusicapi import YTMusic
            ytm = YTMusic()

            vid = extract_youtube_video_id(seed)
            if not vid:
                # If seed is not a video ID or youtube URL, search for the song first
                search_res = ytm.search(seed, filter='songs')
                if search_res and isinstance(search_res, list):
                    first_item = search_res[0]
                    if isinstance(first_item, dict):
                        vid = first_item.get('videoId')

            if not vid:
                return []

            # Add the seed itself to exclude set so we don't repeat it
            exclude.add(vid)

            watch_res = ytm.get_watch_playlist(videoId=vid, limit=max(limit * 3, 10))
            if not watch_res or not isinstance(watch_res, dict):
                return []

            raw_tracks = watch_res.get('tracks')
            if not isinstance(raw_tracks, list):
                return []
            recommendations: List[Dict[str, Any]] = []

            for track in raw_tracks:
                if not isinstance(track, dict):
                    continue

                track_vid = track.get('videoId')
                if not track_vid or track_vid in exclude:
                    continue

                title = track.get('title') or 'Unknown Title'
                artist_objs = track.get('artists')
                artist_names = [a.get('name', '') for a in artist_objs if isinstance(a, dict) and a.get('name')] if isinstance(artist_objs, list) else []
                artist_str = ', '.join(artist_names)

                display_title = title
                if artist_str and artist_str.lower() not in title.lower():
                    display_title = f"{title} - {artist_str}"

                duration = _parse_duration_str(track.get('length'))
                thumbnails = track.get('thumbnail')
                thumbnail_url = None
                if isinstance(thumbnails, list) and thumbnails:
                    last_thumb = thumbnails[-1]
                    if isinstance(last_thumb, dict):
                        thumbnail_url = last_thumb.get('url')

                rec_item = {
                    'id': track_vid,
                    'videoId': track_vid,
                    'title': display_title,
                    'song_title': title,
                    'artist': artist_str,
                    'duration': duration,
                    'url': f"https://www.youtube.com/watch?v={track_vid}",
                    'webpage_url': f"https://www.youtube.com/watch?v={track_vid}",
                    'thumbnail': thumbnail_url,
                    'is_autoplay': True,
                }
                recommendations.append(rec_item)
                exclude.add(track_vid)

                if len(recommendations) >= limit:
                    break

            return recommendations
        except Exception as err:
            print(f"Failed to fetch autoplay recommendations for seed '{seed}': {err}")
            return []

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_sync)