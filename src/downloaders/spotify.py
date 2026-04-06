"""Spotify downloader (SAFE VERSION using yt-dlp fallback)"""

import logging
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
        return bool(
            parsed.netloc and
            'spotify.com' in parsed.netloc.lower()
        )

    async def get_formats(self, url: str) -> List[Dict]:
        return [
            {'id': 'audio', 'quality': 'High Quality Audio', 'ext': 'mp3'}
        ]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """
        🔥 SAFE METHOD:
        - Extract metadata from Spotify
        - Search on YouTube
        - Download via yt-dlp (already optimized in base.py)
        """

        try:
            logger.info(f"[Spotify] Processing via YouTube fallback: {url}")

            # 🔥 Use base downloader logic (yt-dlp)
            metadata, file_path = await super().download(url, "audio")

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
