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
    pass

class BaseDownloader(ABC):
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
        if not self._progress_callback or not self._loop:
            return

        now = self._loop.time()
        # Increase throttle to 2 seconds to be safe
        if now - self._last_progress_time < 2:
            return

        self._last_progress_time = now
        
        # FIXED: Safer thread-safe scheduling
        self._loop.call_soon_threadsafe(
            lambda: asyncio.run_coroutine_threadsafe(
                self._progress_callback(status, progress), self._loop
            )
        )

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
            
            # FIXED: Absolute pathing to avoid globbing the whole directory
            save_path = DOWNLOADS_DIR / temp_filename
            current_opts.update({
                'outtmpl': f"{str(save_path)}.%(ext)s",
                'progress_hooks': [self._progress_hook],
                'nocheckcertificate': True,
                'quiet': True,
                'no_warnings': True,
            })

            # Format Logic
            if format_id == "audio":
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/best"
            elif format_id:
                current_opts['format'] = f"{format_id}+bestaudio/best"

            def _do_download():
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    # extract_info is the heavy lifter
                    return ydl.extract_info(url, download=True)

            # Execute in thread
            info = await asyncio.to_thread(_do_download)

            # FIXED: Direct file check instead of .glob (much faster)
            # yt-dlp provides the actual file path in the info dict
            file_path = Path(info.get('requested_downloads', [{}])[0].get('filepath', ''))
            
            if not file_path.exists():
                # Fallback only if requested_downloads fails
                for ext in ['m4a', 'webm', 'mp3', 'mp4']:
                    fallback = DOWNLOADS_DIR / f"{temp_filename}.{ext}"
                    if fallback.exists():
                        file_path = fallback
                        break

            if not file_path.exists():
                raise DownloadError("Downloaded file disappeared or failed.")

            return self.format_metadata(info), file_path

        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            raise DownloadError(f"Critical Download Error: {str(e)}")
