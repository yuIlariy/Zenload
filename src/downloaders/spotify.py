"""Spotify downloader (FINAL — Non-blocking search)"""

import logging
import asyncio
import aiohttp
import re
import yt_dlp
from urllib.parse import urlparse

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

# GLOBAL OPTIONS: Optimized for speed and event-loop safety
SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": True,  # CRITICAL: prevents deep-scraping each search result
    "skip_download": True,
}

class SpotifyDownloader(BaseDownloader):

    def platform_id(self):
        return 'spotify'

    def can_handle(self, url: str):
        # Specific check for your proxied/custom Spotify URL format
        return "spotify.com" in url

    async def get_formats(self, url):
        return [{'id': 'audio', 'quality': 'High Quality Audio', 'ext': 'm4a/webm'}]

    async def _get_metadata(self, url):
        try:
            api = f"https://open.spotify.com/oembed?url={url}"

            async with aiohttp.ClientSession() as s:
                async with s.get(api) as r:
                    data = await r.json()

            title = data.get("title", "")

            if " - " in title:
                artist, track = title.split(" - ", 1)
                return track.strip(), artist.strip()

            return title, ""

        except Exception:
            return "spotify song", ""

    def _clean(self, text):
        text = text.lower()
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        return text

    def _bad_video(self, title):
        bad_words = ["remix", "live", "cover", "sped", "slowed", "karaoke"]
        return any(w in title for w in bad_words)

    def _score(self, title, track, artist):
        t = self._clean(title)
        score = 0

        if track.lower() in t:
            score += 5
        if artist and artist.lower() in t:
            score += 3
        if "official audio" in t:
            score += 4
        if "topic" in t:
            score += 3
        if self._bad_video(t):
            score -= 5

        return score

    async def _find_best(self, query, track, artist):
        # Runs inside a thread to keep the main bot loop free
        def search():
            # Fresh instance inside thread avoids state-sharing locks
            with yt_dlp.YoutubeDL(SEARCH_OPTS) as ydl:
                return ydl.extract_info(f"ytsearch10:{query}", download=False)

        # Offload the heavy 10-video network lookup
        data = await asyncio.to_thread(search)

        best = None
        best_score = -999

        for e in data.get("entries", []):
            if not e:
                continue
                
            title = e.get("title", "")
            # With extract_flat: True, 'url' is the direct link
            url = e.get("url") or e.get("webpage_url")

            score = self._score(title, track, artist)

            if score > best_score:
                best_score = score
                best = url

        if not best:
            raise DownloadError("No match found for this Spotify track")

        return best

    def _shorten(self, text, limit=70):
        if not text:
            return text
        text = text.strip()
        if len(text) > limit:
            return text[:limit - 3] + "..."
        return text

    async def download(self, url, format_id=None):
        try:
            logger.info(f"[Spotify] Processing: {url}")

            track, artist = await self._get_metadata(url)
            query = f"{artist} {track}".strip()

            logger.info(f"[Spotify] Query: {query}")

            # Find the best match on YouTube (non-blocking)
            best_url = await self._find_best(query, track, artist)
            logger.info(f"[Spotify] Best match: {best_url}")

            # Call parent download (BaseDownloader must use run_coroutine_threadsafe for progress)
            metadata, file_path = await super().download(best_url, "audio")

            short_metadata = self._shorten(metadata, 70)

            caption = (
                f"🎵 <b>{short_metadata}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (Ultra Accurate)\n"
                f"🔗 <a href='{url}'>Watch on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, file_path

        except Exception as e:
            logger.error(f"[Spotify] Failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
