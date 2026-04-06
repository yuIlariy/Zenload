"""Spotify downloader (YouTube search fallback — FINAL FIX)"""

import logging
import re
import asyncio  # ✅ REQUIRED FIX ADDED
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
        return [{'id': 'audio', 'quality': 'High Quality Audio', 'ext': 'mp3'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            logger.info(f"[Spotify] Processing (YouTube search): {url}")

            import yt_dlp

            # 🔥 STEP 1: Extract metadata (NO download)
            ydl_opts = {
                "quiet": True,
                "skip_download": True
            }

            def extract_info():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            try:
                info = await asyncio.to_thread(extract_info)

                title = info.get("title", "")
                artist = info.get("artist") or info.get("uploader") or ""

                query = f"{artist} {title}".strip()

                if not query:
                    raise Exception("Empty metadata")

            except Exception:
                # 🔥 fallback if metadata fails
                query = "spotify song"

            # 🔥 STEP 2: Search YouTube
            search_query = f"ytsearch1:{query}"
            logger.info(f"[Spotify] YouTube search: {search_query}")

            # 🔥 STEP 3: Download via yt-dlp (stable)
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
