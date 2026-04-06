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
        self._last_progress_time = 0

    def set_progress_callback(self, callback: Callable[[str, Any], None]):
        self._progress_callback = callback
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def update_progress(self, status: str, progress: Any):
        # ✅ FIX 1: Ensure loop and callback exist and are valid
        if not self._progress_callback or not self._loop or not self._loop.is_running():
            return

        now = self._loop.time()
        # ✅ FIX 2: Increased throttle. Telegram bots often lag if updated every 2s.
        if now - self._last_progress_time < 3:
            return

        self._last_progress_time = now

        # ✅ FIX 3: Use call_soon_threadsafe to schedule the coroutine creation.
        # This prevents the background thread from ever "waiting" on the loop.
        def schedule_task():
            asyncio.create_task(self._progress_callback(status, progress))

        self._loop.call_soon_threadsafe(schedule_task)

    def _progress_hook(self, d: Dict[str, Any]):
        if d['status'] == 'downloading':
            self.update_progress('downloading', d)

    @abstractmethod
    def platform_id(self) -> str: pass

    @abstractmethod
    def can_handle(self, url: str) -> bool: pass

    @abstractmethod
    async def get_formats(self, url: str) -> List[Dict]: pass

    def format_metadata(self, info: Dict) -> str:
        title = info.get('title') or info.get('description') or "Unknown Title"
        clean_title = re.sub(r'#\w+\s*', '', title).strip()
        uploader = info.get('uploader', 'Unknown')
        return f"{clean_title} | 👤 {uploader}"

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        try:
            current_opts = self.ydl_opts.copy()
            temp_filename = f"zen_{self.platform_id()}_{os.urandom(4).hex()}"
            
            save_path = DOWNLOADS_DIR / temp_filename
            current_opts.update({
                'outtmpl': f"{str(save_path)}.%(ext)s",
                'progress_hooks': [self._progress_hook],
                'nocheckcertificate': True,
                'quiet': True,
                'no_warnings': True,
                'logger': None,  # ✅ FIX 4: Explicitly disable internal logger to prevent GIL hangs
            })

            # Format Logic
            if format_id == "audio":
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/best"
            elif format_id:
                current_opts['format'] = f"{format_id}+bestaudio/best"

            def _do_download():
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            # ✅ FIX 5: Use a proper thread offload
            info = await asyncio.to_thread(_do_download)

            if not info:
                raise DownloadError("Failed to extract information from URL")

            # Direct file check logic
            file_path = None
            req_dl = info.get('requested_downloads', [])
            
            if req_dl and 'filepath' in req_dl[0]:
                file_path = Path(req_dl[0]['filepath'])
            
            # Fallback search limited strictly to the unique temp_filename
            if not file_path or not file_path.exists():
                for ext in ['m4a', 'webm', 'mp3', 'mp4', 'mkv']:
                    fallback = DOWNLOADS_DIR / f"{temp_filename}.{ext}"
                    if fallback.exists():
                        file_path = fallback
                        break

            if not file_path or not file_path.exists():
                raise DownloadError("Download finished but the file could not be located.")

            return self.format_metadata(info), file_path

        except Exception as e:
            logger.error(f"Download failed: {str(e)}", exc_info=True)
            raise DownloadError(f"Download Error: {str(e)}")
