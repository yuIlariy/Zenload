"""Spotify downloader (ULTRA MATCH — best accuracy)"""

import logging
import asyncio
import aiohttp
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)


class SpotifyDownloader(BaseDownloader):

    def platform_id(self) -> str:
        return 'spotify'

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(parsed.netloc and 'spotify.com' in parsed.netloc.lower())

    async def get_formats(self, url: str) -> List[Dict]:
        return [{'id': 'audio', 'quality': 'High Quality Audio', 'ext': 'm4a/webm'}]

    async def _get_spotify_metadata(self, url: str) -> Tuple[str, str]:
        """Get exact track + artist"""
        try:
            api = f"https://open.spotify.com/oembed?url={url}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api) as resp:
                    data = await resp.json()

            title = data.get("title", "")

            if " - " in title:
                artist, track = title.split(" - ", 1)
                return track.strip(), artist.strip()

            return title.strip(), ""

        except Exception:
            return "spotify song", ""

    def _clean(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"official|video|lyrics|audio", "", text)
        return text.strip()

    def _score(self, yt_title: str, track: str, artist: str) -> int:
        yt = self._clean(yt_title)
        score = 0

        if track.lower() in yt:
            score += 3

        if artist and artist.lower() in yt:
            score += 2

        return score

    async def _find_best_match(self, query: str, track: str, artist: str) -> str:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "skip_download": True
        }

        def search():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(f"ytsearch5:{query}", download=False)

        data = await asyncio.to_thread(search)

        best_url = None
        best_score = -1

        for entry in data.get("entries", []):
            title = entry.get("title", "")
            url = entry.get("webpage_url")

            score = self._score(title, track, artist)

            if score > best_score:
                best_score = score
                best_url = url

        if not best_url:
            raise DownloadError("No suitable YouTube match found")

        return best_url

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, str]:
        try:
            logger.info(f"[Spotify] Processing: {url}")

            # 🔥 STEP 1: exact metadata
            track, artist = await self._get_spotify_metadata(url)

            query = f"{artist} {track}".strip()
            logger.info(f"[Spotify] Query: {query}")

            # 🔥 STEP 2: find BEST match
            best_url = await self._find_best_match(query, track, artist)
            logger.info(f"[Spotify] Best match: {best_url}")

            # 🔥 STEP 3: download (NO conversion)
            metadata, file_path = await super().download(best_url, "audio")

            caption = (
                f"🎵 <b>{metadata}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (Ultra Matched)\n"
                f"🔗 <a href='{url}'>Watch on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, file_path

        except Exception as e:
            logger.error(f"[Spotify] Failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
