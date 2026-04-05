"""Pinterest downloader - Cobalt primary, yt-dlp fallback"""

import logging
import asyncio
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import yt_dlp
from .base import BaseDownloader, DownloadError
from ..utils.cobalt_service import cobalt

logger = logging.getLogger(__name__)

class PinterestDownloader(BaseDownloader):
    def __init__(self):
        super().__init__()

    def platform_id(self) -> str:
        return 'pinterest'

    def can_handle(self, url: str) -> bool:
        return any(x in url.lower() for x in ['pinterest.com', 'pin.it'])

    async def get_formats(self, url: str) -> List[Dict]:
        """Simple format check for the menu"""
        self.update_progress('status_getting_info', 0)
        return [{'id': 'best', 'quality': 'Best', 'ext': 'mp4'}]

    async def download(self, url: str, format_id: Optional[str] = None) -> Tuple[str, Path]:
        """Download video - Cobalt first, yt-dlp fallback"""
        logger.info(f"[Pinterest] Downloading: {url}")
        download_dir = Path(__file__).parent.parent.parent / "downloads"
        download_dir.mkdir(exist_ok=True)
        
        # --- 1. Try Cobalt First (Most efficient) ---
        self.update_progress('status_downloading', 10)
        filename, file_path = await cobalt.download(
            url, 
            download_dir,
            progress_callback=self.update_progress
        )
        
        # If Cobalt works, we still need a title. We'll use a very safe default 
        # to avoid hitting the URL again and getting blocked.
        if file_path and file_path.exists():
            caption = (
                f"🎬 <b>Pinterest Video</b>\n\n"
                f"⚡ Pinterest\n"
                f"✨ By Pinterest User\n\n"
                f"📥 Downloader: @Tik_TokDownloader_Bot"
            )
            return caption, file_path
        
        # --- 2. Fallback to yt-dlp (Single Request) ---
        logger.info("[Pinterest] Cobalt failed, trying yt-dlp fallback")
        self.update_progress('status_downloading', 30)
        
        try:
            # DO NOT call get_info here. Go straight to download.
            ydl_opts = {
                'format': 'best', # Don't force a specific ID, Pinterest changes them
                'outtmpl': str(download_dir / '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            
            def download_video():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # extract_info with download=True returns the data AND saves the file
                    return ydl.extract_info(url, download=True)
            
            info = await asyncio.to_thread(download_video)
            
            if info:
                # Extract title and uploader FROM THE DOWNLOADED INFO
                title = info.get('title') or info.get('description') or "Pinterest Video"
                uploader = info.get('uploader') or "Pinterest"
                
                if len(title) > 800:
                    title = title[:797] + "..."

                caption = (
                    f"🎬 <b>{title}</b>\n\n"
                    f"⚡ Pinterest\n"
                    f"✨ By {uploader}\n\n"
                    f"📥 Downloader: @Tik_TokDownloader_Bot"
                )

                actual_filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
                file_path = Path(actual_filename).resolve()
                
                if file_path.exists():
                    return caption, file_path
            
            raise DownloadError("File downloaded but not found")
            
        except Exception as e:
            logger.error(f"[Pinterest] yt-dlp failed: {e}")
            raise DownloadError(f"Ошибка загрузки: {str(e)}")
