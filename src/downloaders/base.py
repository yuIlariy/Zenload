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
        # Load platform-specific options
        self.ydl_opts = YTDLP_OPTIONS.get(self.platform_id(), {}).copy()
        self.ydl_opts.pop('format', None)

        self._progress_callback = None
        self._loop = None

    def set_progress_callback(self, callback: Callable[[str, Any], None]):
        """Set callback for progress updates"""
        self._progress_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def update_progress(self, status: str, progress: Any):
        """Update progress safely across threads"""
        if self._progress_callback:
            if self._loop:
                # If in main loop, call directly; otherwise, use threadsafe
                if asyncio.get_event_loop() == self._loop:
                    asyncio.create_task(self._progress_callback(status, progress))
                else:
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self._progress_callback(status, progress))
                    )

    def _progress_hook(self, d: Dict[str, Any]):
        """Standard progress hook for yt-dlp"""
        if d['status'] == 'downloading' and self._progress_callback:
            # Pass the whole dictionary to allow DownloadWorker to calculate speed/ETA
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
        """Improved metadata formatting"""
        metadata = []
        
        # Use description for TikTok/Shorts if title is generic
        title = info.get('description') or info.get('title')
        if title:
            clean_title = re.sub(r'#\w+\s*', '', title).strip()
            metadata.append(clean_title if clean_title else title)

        if uploader := info.get('uploader'):
            metadata.append(f"👤 {uploader}")

        return " | ".join(metadata)

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download content with support for native m4a"""
        try:
            url = self.preprocess_url(url)
            current_opts = self.ydl_opts.copy()

            temp_filename = f"zen_{self.platform_id()}_{os.urandom(4).hex()}"
            current_opts['outtmpl'] = str(DOWNLOADS_DIR / f"{temp_filename}.%(ext)s")
            current_opts['progress_hooks'] = [self._progress_hook]

            # 🔥 DYNAMIC FORMAT HANDLING
            if format_id == "m4a":
                # Download native AAC stream without conversion
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio/best"
            elif format_id == "audio":
                # Standard MP3 conversion fallback
                current_opts['format'] = "bestaudio/best"
                current_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            elif format_id:
                current_opts['format'] = f"{format_id}+bestaudio/best"
            else:
                current_opts['format'] = "bestvideo+bestaudio/best"

            def download_content():
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            # Offload blocking download to thread
            info = await asyncio.to_thread(download_content)

            if not info:
                raise DownloadError("Failed to get content information")

            # Find file
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
