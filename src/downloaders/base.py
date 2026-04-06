import os
import logging
import re
import asyncio
from typing import Tuple, Dict, List, Callable, Any, Optional
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
        self.ydl_opts = YTDLP_OPTIONS.get(self.platform_id(), {}).copy()
        self.ydl_opts.pop('format', None)

        self._progress_callback = None
        self._loop = None

        # 🔥 Throttle progress updates
        self._last_progress_time = 0

    def set_progress_callback(self, callback: Callable[[str, Any], None]):
        self._progress_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def update_progress(self, status: str, progress: Any):
        if not self._progress_callback:
            return

        try:
            loop = self._loop or asyncio.get_event_loop()
            now = loop.time()

            # 🔥 limit updates (prevents freeze)
            if now - self._last_progress_time < 1:
                return

            self._last_progress_time = now

            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._progress_callback(status, progress))
                )

        except RuntimeError:
            pass

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading' and self._progress_callback:
            self.update_progress('downloading', d)

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
        metadata = []

        title = info.get('description') or info.get('title')
        if title:
            clean_title = re.sub(r'#\w+\s*', '', title).strip()
            metadata.append(clean_title if clean_title else title)

        if uploader := info.get('uploader'):
            metadata.append(f"👤 {uploader}")

        return " | ".join(metadata)

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            url = self.preprocess_url(url)
            current_opts = self.ydl_opts.copy()

            temp_filename = f"zen_{self.platform_id()}_{os.urandom(4).hex()}"
            current_opts['outtmpl'] = str(DOWNLOADS_DIR / f"{temp_filename}.%(ext)s")
            current_opts['progress_hooks'] = [self._progress_hook]

            # 🔥 FIXED FORMAT HANDLING (NO FFmpeg)
            if format_id == "m4a":
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio/best"

            elif format_id == "audio":
                # 🔥 NO CONVERSION → prevents freezing
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"

            elif format_id:
                current_opts['format'] = f"{format_id}+bestaudio/best"

            else:
                current_opts['format'] = "bestvideo+bestaudio/best"

            def download_content():
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            info = await asyncio.to_thread(download_content)

            if not info:
                raise DownloadError("Failed to get content information")

            downloaded_file = None
            for file in DOWNLOADS_DIR.glob(f"{temp_filename}.*"):
                if file.is_file():
                    downloaded_file = file
                    break

            if not downloaded_file:
                raise DownloadError("File downloaded but not found")

            return self.format_metadata(info), downloaded_file

        except Exception as e:
            logger.error(f"Download failed for {url}: {str(e)}", exc_info=True)
            raise DownloadError(f"Download error: {str(e)}")
