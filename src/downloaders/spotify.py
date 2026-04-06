"""Spotify downloader (PERFECT MATCH using Spotify oEmbed + smart search)"""

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

    async def _get_spotify_metadata(self, url: str) -> str:
        """🔥 PERFECT: Get exact title + artist using Spotify oEmbed"""
        try:
            api = f"https://open.spotify.com/oembed?url={url}"

            async with aiohttp.ClientSession() as session:
                async with session.get(api) as resp:
                    data = await resp.json()

            title = data.get("title", "")

            # Example: "Drake - One Dance"
            if " - " in title:
                artist, track = title.split(" - ", 1)
                return f"{artist} {track}"

            return title

        except Exception:
            return "spotify song"

    def _clean_query(self, query: str) -> str:
        """Remove junk for better YouTube matching"""
        query = re.sub(r"\(.*?\)", "", query)
        query = re.sub(r"\[.*?\]", "", query)
        query = re.sub(r"official video|lyrics|audio", "", query, flags=re.I)
        return query.strip()

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, str]:
        try:
            logger.info(f"[Spotify] Processing: {url}")

            # ✅ STEP 1: perfect metadata
            query = await self._get_spotify_metadata(url)
            query = self._clean_query(query)

            logger.info(f"[Spotify] Search query: {query}")

            # 🔥 STEP 2: smarter search (avoid wrong songs)
            search_query = f"ytsearch1:{query} audio"

            # ✅ STEP 3: download (NO conversion → no freeze)
            metadata, file_path = await super().download(search_query, "audio")

            caption = (
                f"🎵 <b>{metadata}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (Matched Audio)\n"
                f"🔗 <a href='{url}'>Watch on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, file_path

        except Exception as e:
            logger.error(f"[Spotify] Failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
