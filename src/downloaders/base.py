import os
import logging
import re
import asyncio
from typing import Tuple, Dict, List, Callable, Any
from pathlib import Path
from abc import ABC, abstractmethod
import yt_dlp

from ..config import YTDLP_OPTIONS, DOWNLOADS_DIR

logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Custom exception for download errors"""
    pass


class BaseDownloader(ABC):
    """Base class for all platform-specific downloaders"""

    def __init__(self):
        # Load platform-specific options
        self.ydl_opts = YTDLP_OPTIONS.get(self.platform_id(), {}).copy()

        # 🔥 Remove forced format (important)
        self.ydl_opts.pop('format', None)

        self._progress_callback = None
        self._loop = None

    def set_progress_callback(self, callback: Callable[[str, int], None]):
        """Set callback for progress updates"""
        self._progress_callback = callback
        self._loop = asyncio.get_running_loop()

    def update_progress(self, status: str, progress: int):
        """Update download progress asynchronously"""
        if self._progress_callback and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._progress_callback(status, progress),
                self._loop
            )

    def _progress_hook(self, d: Dict[str, Any]):
        """Progress hook for yt-dlp"""
        if d['status'] == 'downloading' and self._progress_callback:
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                downloaded = d.get('downloaded_bytes', 0)

                if total > 0:
                    progress = int((downloaded / total) * 80) + 10
                    self.update_progress('status_downloading', progress)

            except Exception as e:
                logger.error(f"Error in progress hook: {e}")

    @staticmethod
    def _prepare_filename(title: str) -> str:
        """Prepare safe filename"""
        safe_title = re.sub(r'[<>:"/\\|?*]', '', title)
        return safe_title[:100]

    @abstractmethod
    def platform_id(self) -> str:
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        pass

    def preprocess_url(self, url: str) -> str:
        return url

    @abstractmethod
    async def get_formats(self, url: str) -> List[Dict]:
        pass

    def format_metadata(self, info: Dict) -> str:
        """Format metadata"""
        metadata = []

        if title := info.get('title'):
            clean_title = re.sub(r'#\w+\s*', '', title).strip()
            if clean_title:
                metadata.append(clean_title)

        if uploader := info.get('uploader'):
            metadata.append(f"By: {uploader}")

        if view_count := info.get('view_count'):
            if view_count >= 1_000_000:
                metadata.append(f"Views: {view_count/1_000_000:.1f}M")
            elif view_count >= 1_000:
                metadata.append(f"Views: {view_count/1_000:.1f}K")
            else:
                metadata.append(f"Views: {view_count}")

        return " | ".join(metadata)

    async def download(self, url: str, format_id: str = None) -> Tuple[str, Path]:
        """Download content with safe fallback handling"""
        try:
            self.update_progress('status_downloading', 0)
            url = self.preprocess_url(url)

            current_opts = self.ydl_opts.copy()

            temp_filename = f"zen_{self.platform_id()}_{os.urandom(4).hex()}"
            current_opts['outtmpl'] = str(DOWNLOADS_DIR / f"{temp_filename}.%(ext)s")

            # 🔥 FIXED FORMAT HANDLING
            if format_id == "audio":
                current_opts['format'] = "bestaudio/best"
                current_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            elif format_id:
                current_opts['format'] = (
                    f"{format_id}+bestaudio/"
                    f"{format_id}/"
                    f"bestvideo+bestaudio/"
                    f"best"
                )
            else:
                current_opts['format'] = "bestvideo+bestaudio/best"

            current_opts['progress_hooks'] = [self._progress_hook]

            def download_content():
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            info = await asyncio.to_thread(download_content)

            if not info:
                raise DownloadError("Failed to get content information")

            # 🔍 Find downloaded file safely
            downloaded_file = None
            for file in DOWNLOADS_DIR.glob(f"{temp_filename}.*"):
                if file.is_file():
                    downloaded_file = file
                    break

            if not downloaded_file:
                raise DownloadError("File was downloaded but not found")

            self.update_progress('status_downloading', 100)

            return self.format_metadata(info), downloaded_file

        except Exception as e:
            logger.error(f"Download failed for {url}: {str(e)}", exc_info=True)
            raise DownloadError(f"Download error: {str(e)}")
