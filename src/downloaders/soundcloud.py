import logging
import re
from pathlib import Path
from typing import Tuple, Dict, List, Optional

from .base import BaseDownloader, DownloadError

logger = logging.getLogger(__name__)

class SoundcloudDownloader(BaseDownloader):
    """Downloader powered by yt-dlp through BaseDownloader."""

    _url_pattern = re.compile(r"(soundcloud\.com|sndcdn\.com)", re.IGNORECASE)

    def platform_id(self) -> str:
        return "soundcloud"

    def can_handle(self, url: str) -> bool:
        return bool(url and self._url_pattern.search(url))

    async def get_formats(self, url: str) -> List[Dict]:
        return [
            {
                "id": "audio",
                "quality": "Best Available Audio",
                "ext": "m4a/opus",
            }
        ]

    def format_metadata(self, info: Dict) -> str:
        """Overrides base.py metadata formatting to use your custom SoundCloud layout"""
        # Extract title and artist directly from yt-dlp info dict
        title = info.get("title") or "SoundCloud Track"
        artist = info.get("uploader") or info.get("creator") or "Unknown Artist"
        
        # Format play count (Plays)
        play_count_str = ""
        # yt-dlp usually stores plays in view_count or playback_count
        play_count = info.get("view_count") or info.get("playback_count")
        if play_count:
            if play_count >= 1_000_000:
                play_count_str = f"{play_count/1_000_000:.1f}M"
            elif play_count >= 1_000:
                play_count_str = f"{play_count/1_000:.1f}K"
            else:
                play_count_str = str(play_count)

        # Safety: Truncate title for Telegram limits (1024 chars)
        if len(title) > 800:
            title = title[:797] + "..."

        # Build professional caption matching your original style
        caption_parts = [
            f"🎬 <b>{title}</b>\n",
            f"☁️ SoundCloud"
        ]
        
        if play_count_str:
            caption_parts[1] += f" | {play_count_str} Plays"
            
        caption_parts.append(f"✨ By {artist}\n")
        caption_parts.append(f"📥 <b>@Tik_TokDownloader_Bot</b>")

        return "\n".join(caption_parts)

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            logger.info(f"[SoundCloud] Processing: {url}")
            
            # BaseDownloader automatically handles the yt-dlp extraction, 
            # uses your WARP proxy, safely manages threads, and calls format_metadata() above.
            metadata, file_path = await super().download(url, "audio")

            return metadata, file_path

        except Exception as e:
            logger.error(f"Error downloading from SoundCloud: {e}", exc_info=True)
            raise DownloadError(f"Site protected or track unavailable. Error: {e}")
