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
        # 2-second throttle is good for Telegram bots to prevent flood/freeze
        if now - self._last_progress_time < 2:
            return

        self._last_progress_time = now
        
        # ✅ FIXED: Use run_coroutine_threadsafe ALONE. 
        # Do not nest it inside call_soon_threadsafe.
        asyncio.run_coroutine_threadsafe(
            self._progress_callback(status, progress), self._loop
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
            
            save_path = DOWNLOADS_DIR / temp_filename
            current_opts.update({
                'outtmpl': f"{str(save_path)}.%(ext)s",
                'progress_hooks': [self._progress_hook],
                'nocheckcertificate': True,
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False, # Ensure we actually get the file for download
            })

            # Format Logic
            if format_id == "audio":
                current_opts['format'] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/best"
            elif format_id:
                current_opts['format'] = f"{format_id}+bestaudio/best"

            def _do_download():
                # Re-initializing here ensures no thread-leakage
                with yt_dlp.YoutubeDL(current_opts) as ydl:
                    return ydl.extract_info(url, download=True)

            # Move heavy blocking network/IO to thread
            info = await asyncio.to_thread(_do_download)

            # ✅ FIXED: Improved path finding
            file_path = None
            req_dl = info.get('requested_downloads', [])
            if req_dl:
                file_path = Path(req_dl[0].get('filepath', ''))

            if not file_path or not file_path.exists():
                # Fallback search limited strictly to the unique temp_filename
                for ext in ['m4a', 'webm', 'mp3', 'mp4', 'mkv']:
                    fallback = DOWNLOADS_DIR / f"{temp_filename}.{ext}"
                    if fallback.exists():
                        file_path = fallback
                        break

            if not file_path or not file_path.exists():
                raise DownloadError("Download finished but file not found on disk.")

            return self.format_metadata(info), file_path

        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            raise DownloadError(f"Critical Download Error: {str(e)}")
