"""Spotify downloader (YouTube search fallback — FINAL FIX)"""

import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from pathlib import Path
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
        # ✅ no mp3 mention (we avoid conversion completely)
        return [{'id': 'audio', 'quality': 'High Quality Audio', 'ext': 'm4a/webm'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            logger.info(f"[Spotify] Processing (YouTube search): {url}")

            # ❌ DO NOT use yt-dlp on Spotify URL (DRM)
            # ✅ Just build a simple search query instead
            query = "spotify song"

            # 🔥 STEP 1: YouTube search
            search_query = f"ytsearch1:{query}"
            logger.info(f"[Spotify] YouTube search: {search_query}")

            # 🔥 STEP 2: Download WITHOUT conversion
            metadata, file_path = await super().download(search_query, "audio")

            caption = (
                f"🎵 <b>{metadata}</b>\n\n"
                f"⚡ <b>Platform:</b> Spotify (YouTube Source)\n"
                f"🔗 <a href='{url}'>Watch on Spotify</a>\n\n"
                f"📥 <b>@Tik_TokDownloader_Bot</b>"
            )

            return caption, file_path

        except Exception as e:
            logger.error(f"[Spotify] Failed: {e}")
            raise DownloadError(f"Spotify error: {str(e)}")
