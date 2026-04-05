import logging
import re
from pathlib import Path
from typing import Tuple, Dict, List

from .base import BaseDownloader, DownloadError
from ..config import DOWNLOADS_DIR
from ..utils.soundcloud_service import SoundcloudService

logger = logging.getLogger(__name__)


class SoundcloudDownloader(BaseDownloader):
    """Downloader powered by soundcloud-v2 library."""

    _url_pattern = re.compile(r"(soundcloud\.com|sndcdn\.com)", re.IGNORECASE)

    def __init__(self):
        super().__init__()
        self.service = SoundcloudService.get_instance()

    def platform_id(self) -> str:
        return "soundcloud"

    def can_handle(self, url: str) -> bool:
        return bool(url and self._url_pattern.search(url))

    async def get_formats(self, url: str) -> List[Dict]:
        # SoundCloud public API only exposes a single mp3-ish stream
        return [
            {
                "id": "mp3",
                "quality": "MP3 128-160 kbps",
                "ext": "mp3",
            }
        ]

    async def _get_track_info(self, url: str) -> Tuple[Dict, Path, str]:
        """Resolve URL, select stream URL, and compute target path."""
        track_meta = await self.service.resolve_track(url)
        if not track_meta or track_meta.get("kind") != "track":
            raise DownloadError("Track not found or unsupported")

        stream_url = await self.service.get_stream_url(track_meta)
        if not stream_url:
            raise DownloadError("No downloadable stream found for this track")

        ext = "mp3"
        title = track_meta.get("title") or "SoundCloud Track"
        artist = ""
        user_info = track_meta.get("user") or {}
        if isinstance(user_info, dict):
            artist = user_info.get("username") or user_info.get("full_name") or ""

        filename = f"{artist + ' - ' if artist else ''}{title}.{ext}"
        safe_name = self._prepare_filename(filename)
        file_path = DOWNLOADS_DIR / safe_name
        return track_meta, file_path, stream_url

    def _format_metadata(self, track_meta: Dict) -> str:
        # Extract title and artist with safe fallbacks
        title = track_meta.get("title") or "SoundCloud Track"
        user_info = track_meta.get("user") or {}
        artist = user_info.get("username") or user_info.get("full_name") or "Unknown Artist"
        
        # Format play count (Plays)
        play_count_str = ""
        play_count = track_meta.get("playback_count")
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

        # Build professional caption
        caption_parts = [
            f"🎬 <b>{title}</b>\n",
            f"☁️ SoundCloud"
        ]
        
        if play_count_str:
            caption_parts[1] += f" | {play_count_str} Plays"
            
        caption_parts.append(f"✨ By {artist}\n")
        caption_parts.append(f"📥 Downloader: @Tik_TokDownloader_Bot")

        return "\n".join(caption_parts)

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        try:
            self.update_progress("status_downloading", 5)
            track_meta, file_path, stream_url = await self._get_track_info(url)

            downloaded = 0
            total_size = 0

            session = await self.service._get_session()
            async with session.get(stream_url) as resp:
                resp.raise_for_status()
                total_size = int(resp.headers.get("Content-Length") or 0)
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size:
                            progress = min(100, max(10, int(downloaded / total_size * 90)))
                            self.update_progress("status_downloading", progress)

            self.update_progress("status_downloading", 100)

            metadata = self._format_metadata(track_meta)
            return metadata, file_path
        except Exception as e:
            logger.error(f"Error downloading from SoundCloud: {e}", exc_info=True)
            raise DownloadError(f"Download error: {e}")
